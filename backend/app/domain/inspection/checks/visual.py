"""Visual quality checks (Phase 8): defects you can only see on the rendered page.

They work on the geometry recorded when the document was rendered (``ctx.layout``): text spans
with colour and sampled background, image boxes and drawing rectangles. Each finding is grouped
per page and carries the offending boxes in ``actual["boxes"]`` so the UI can draw them on the
page image. Layouts rendered before Phase 8 lack colours and drawing rects; checks that need
those report themselves as not evaluated instead of guessing.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from app.domain.inspection.engine import NotEvaluated, check
from app.domain.inspection.model import Finding, InspectContext

ALL = ("docx", "pdf", "pptx", "generated")
PAGED = ("docx", "pdf", "generated")
Box = tuple[float, float, float, float]
MAX_BOXES = 20


def _pages(ctx: InspectContext) -> list[dict[str, Any]]:
    pages = (ctx.layout or {}).get("pages") or []
    if not pages:
        raise NotEvaluated("The pages were not rendered, so the visual checks cannot run.")
    if any("width_pt" not in p or "height_pt" not in p for p in pages):
        raise NotEvaluated("The render has no page sizes; re-run the analysis.")
    return list(pages)


def _union(boxes: list[Box]) -> Box:
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _label(ctx: InspectContext, i: int) -> str:
    return f"slide {i + 1}" if ctx.adm.source_format == "pptx" else f"page {i + 1}"


def _finding(ctx: InspectContext, page: int, boxes: list[Box], **kw: Any) -> Finding:
    actual = {"boxes": [list(b) for b in boxes[:MAX_BOXES]], "count": len(boxes), **kw.pop("actual", {})}
    return Finding(
        category="visual",
        detector="visual",
        page=page,
        bbox=_union(boxes) if boxes else None,
        location=_label(ctx, page).capitalize(),
        actual=actual,
        **kw,
    )


# --------------------------------------------------------------------------- off the page


@check("VIS.CONTENT_OFF_PAGE", formats=ALL)
def off_page(ctx: InspectContext) -> list[Finding]:
    out: list[Finding] = []
    for p in _pages(ctx):
        w, h, tol = p["width_pt"], p["height_pt"], 1.0
        boxes: list[Box] = []
        for b in [*(s["bbox"] for s in p.get("spans", [])), *p.get("images", [])]:
            x0, y0, x1, y1 = b
            if x0 < -tol or y0 < -tol or x1 > w + tol or y1 > h + tol:
                boxes.append((x0, y0, x1, y1))
        if boxes:
            out.append(
                _finding(
                    ctx,
                    p["index"],
                    boxes,
                    code="VIS.CONTENT_OFF_PAGE",
                    severity="high",
                    message=f"{len(boxes)} item(s) run past the edge of {_label(ctx, p['index'])} and are cut off.",
                    explanation="Content outside the page is clipped when printed or exported to PDF.",
                    recommendation="Move or resize the item so it sits fully inside the page.",
                )
            )
    return out


# --------------------------------------------------------------------------- margins


def _content_box(ctx: InspectContext, pages: list[dict[str, Any]]) -> tuple[float, float, float, bool]:
    """Left and right limit of the text area (pt from the left edge) and whether they are exact."""
    setups = [s for s in ctx.adm.page_setups if s.margins]
    widths = {round(p["width_pt"]) for p in pages}
    if ctx.exact and setups and len({(s.margins.left, s.margins.right) for s in setups if s.margins}) == 1:
        m = setups[0].margins
        assert m is not None
        width = pages[0]["width_pt"]
        if len(widths) == 1:
            return m.left, width - m.right, width, True
    xs0 = sorted(s["bbox"][0] for p in pages for s in p.get("spans", []))
    xs1 = sorted(s["bbox"][2] for p in pages for s in p.get("spans", []))
    if len(xs1) < 40 or len(widths) != 1:
        raise NotEvaluated("Not enough text to infer the margins reliably.")
    return xs0[len(xs0) // 20], xs1[len(xs1) * 19 // 20], pages[0]["width_pt"], False


@check("VIS.MARGIN_INTRUSION", formats=PAGED)
def margin_intrusion(ctx: InspectContext) -> list[Finding]:
    pages = _pages(ctx)
    left, right, width, exact = _content_box(ctx, pages)
    tol = 9.0 if exact else 18.0  # Word lets table cell padding sit ~5.4 pt outside the text area
    out: list[Finding] = []
    for p in pages:
        h = p["height_pt"]
        kinds: Counter[str] = Counter()
        boxes: list[Box] = []
        items: list[tuple[str, Box]] = [
            *(("text", tuple(s["bbox"])) for s in p.get("spans", [])),
            *(("image", tuple(b)) for b in p.get("images", [])),
            *(("table or shape", tuple(b)) for b in p.get("drawings", [])),
        ]
        for kind, b in items:
            x0, y0, x1, y1 = b
            if y1 < h * 0.08 or y0 > h * 0.92:  # header / footer band
                continue
            if x1 - x0 > width * 0.97:  # full-width rules and page backgrounds
                continue
            if x1 > right + tol or x0 < left - tol:
                kinds[kind] += 1
                boxes.append((x0, y0, x1, y1))
        if not boxes:
            continue
        worst = max(max(b[2] - right, left - b[0]) for b in boxes)
        what = ", ".join(k for k, _ in kinds.most_common())
        out.append(
            _finding(
                ctx,
                p["index"],
                boxes,
                code="VIS.MARGIN_INTRUSION",
                severity="medium",
                message=f"Content ({what}) extends up to {worst:.0f} pt into the margin on {_label(ctx, p['index'])}.",
                explanation="Margins keep content clear of binding and trimming and are usually required by "
                "submission standards.",
                recommendation="Resize the table or image to the text width, or let long text wrap.",
                expected={"left_pt": round(left, 1), "right_pt": round(right, 1)},
                confidence=1.0 if exact else 0.7,
                actual={"worst_pt": round(worst, 1)},
            )
        )
    return out


# --------------------------------------------------------------------------- empty pages


@check("VIS.BLANK_PAGE", formats=PAGED)
def blank_pages(ctx: InspectContext) -> list[Finding]:
    pages = _pages(ctx)
    return [
        _finding(
            ctx,
            p["index"],
            [],
            code="VIS.BLANK_PAGE",
            severity="medium",
            message=f"{_label(ctx, p['index']).capitalize()} is blank apart from its header or footer.",
            explanation="Unintended blank pages usually come from stray page or section breaks.",
            recommendation="Remove the extra page break, or the empty paragraphs before a break.",
        )
        for p in pages
        if _empty_body(p)
    ]


def _empty_body(p: dict[str, Any]) -> bool:
    """Nothing but (optionally) a header or footer — e.g. a page holding only its page number."""
    if p.get("blank"):
        return True
    h = p["height_pt"]
    body = [s for s in p.get("spans", []) if h * 0.08 < s["bbox"][1] and s["bbox"][3] < h * 0.92]
    shapes = [b for b in p.get("drawings", []) if h * 0.08 < b[1] and b[3] < h * 0.92]
    return not body and not p.get("images") and not shapes


@check("VIS.SPARSE_PAGE", formats=PAGED)
def sparse_pages(ctx: InspectContext) -> list[Finding]:
    pages = _pages(ctx)
    out: list[Finding] = []
    for prev, p, nxt in zip(pages, pages[1:], pages[2:], strict=False):
        lines = {round(s["bbox"][3]) for s in p.get("spans", [])}
        body = [s for s in p.get("spans", []) if p["height_pt"] * 0.08 < s["bbox"][1] < p["height_pt"] * 0.92]
        body_lines = {round(s["bbox"][3]) for s in body}
        full_before = len({round(s["bbox"][3]) for s in prev.get("spans", [])}) >= 25
        if 0 < len(body_lines) <= 2 and len(lines) <= 4 and full_before and not p.get("images") and nxt.get("spans"):
            out.append(
                _finding(
                    ctx,
                    p["index"],
                    [tuple(s["bbox"]) for s in body],
                    code="VIS.SPARSE_PAGE",
                    severity="low",
                    message=f"{_label(ctx, p['index']).capitalize()} holds only {len(body_lines)} line(s) of text.",
                    explanation="A line or two carried over onto an otherwise empty page looks unfinished and "
                    "wastes a page.",
                    recommendation="Tighten the previous page, or keep the paragraph together with the next one.",
                    confidence=0.8,
                )
            )
    return out


# --------------------------------------------------------------------------- overlaps


def _area(b: Box) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


@check("VIS.TEXT_OVERLAP", formats=ALL)
def overlaps(ctx: InspectContext) -> list[Finding]:
    out: list[Finding] = []
    for p in _pages(ctx):
        spans: list[Box] = sorted((tuple(s["bbox"]) for s in p.get("spans", [])), key=lambda b: b[1])
        hits: list[Box] = []
        for i, a in enumerate(spans):
            for b in spans[i + 1 :]:
                if b[1] >= a[3]:
                    break
                ix = min(a[2], b[2]) - max(a[0], b[0])
                iy = min(a[3], b[3]) - max(a[1], b[1])
                if ix <= 0 or iy <= 0:
                    continue
                same_line = abs(a[3] - b[3]) < 1.0 and abs(a[1] - b[1]) < 1.0
                small = min(_area(a), _area(b))
                if not same_line and small > 0 and ix * iy / small > 0.35:
                    hits.extend([a, b])
        if hits:
            uniq = list(dict.fromkeys(hits))
            out.append(
                _finding(
                    ctx,
                    p["index"],
                    uniq,
                    code="VIS.TEXT_OVERLAP",
                    severity="high" if ctx.adm.source_format == "pptx" else "medium",
                    message=f"Text overlaps other text on {_label(ctx, p['index'])}.",
                    explanation="Overlapping text is unreadable and usually means a text box grew past its space.",
                    recommendation="Move the boxes apart, shorten the text, or let one box flow below the other.",
                )
            )
    return out


# --------------------------------------------------------------------------- contrast


def _lum(c: int) -> float:
    def ch(v: int) -> float:
        s = v / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    return 0.2126 * ch((c >> 16) & 255) + 0.7152 * ch((c >> 8) & 255) + 0.0722 * ch(c & 255)


def contrast_ratio(fg: int, bg: int) -> float:
    a, b = sorted((_lum(fg), _lum(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


@check("VIS.LOW_CONTRAST", formats=ALL)
def low_contrast(ctx: InspectContext) -> list[Finding]:
    pages = _pages(ctx)
    if not any("bg" in s for p in pages for s in p.get("spans", [])):
        raise NotEvaluated("This render predates colour sampling; re-run the analysis to check contrast.")
    out: list[Finding] = []
    for p in pages:
        boxes: list[Box] = []
        worst = 21.0
        for s in p.get("spans", []):
            if s.get("bg") is None or len(s["text"].strip()) < 2:
                continue
            large = s["size"] >= 18 or (s["size"] >= 14 and "bold" in s.get("font", "").lower())
            need = 3.0 if large else 4.5  # WCAG 2.x AA
            r = contrast_ratio(int(s.get("color", 0)), int(s["bg"]))
            if r < need:
                boxes.append(tuple(s["bbox"]))
                worst = min(worst, r)
        if boxes:
            out.append(
                _finding(
                    ctx,
                    p["index"],
                    boxes,
                    code="VIS.LOW_CONTRAST",
                    severity="medium",
                    message=f"{len(boxes)} text run(s) on {_label(ctx, p['index'])} have low contrast "
                    f"(as low as {worst:.1f}:1).",
                    explanation="Low-contrast text is hard to read, especially when projected or printed in grey.",
                    recommendation="Use a darker text colour on light backgrounds (or lighter on dark).",
                    expected="≥ 4.5:1 (≥ 3:1 for large text), WCAG AA",
                    confidence=0.9,  # background is sampled from the rendered image
                    actual={"worst_ratio": round(worst, 2)},
                )
            )
    return out


# --------------------------------------------------------------------------- alignment


@check("VIS.ALIGNMENT", formats=PAGED)
def alignment(ctx: InspectContext) -> list[Finding]:
    pages = _pages(ctx)
    sizes = Counter(round(s["size"]) for p in pages for s in p.get("spans", []))
    if not sizes:
        return []
    body = sizes.most_common(1)[0][0]
    # line starts of body-size text: (page, x0, x1, bbox)
    starts: list[tuple[int, float, Box]] = []
    for p in pages:
        lines: dict[int, list[dict[str, Any]]] = {}
        for s in p.get("spans", []):
            if abs(s["size"] - body) <= 0.6:
                lines.setdefault(round(s["bbox"][3]), []).append(s)
        mid = p["width_pt"] / 2
        for spans in lines.values():
            x0 = min(s["bbox"][0] for s in spans)
            x1 = max(s["bbox"][2] for s in spans)
            if abs((x0 + x1) / 2 - mid) < 3 and x0 > 100:  # centred lines (titles, captions)
                continue
            box = (x0, min(s["bbox"][1] for s in spans), x1, max(s["bbox"][3] for s in spans))
            starts.append((p["index"], x0, box))
    if len(starts) < 30:
        return []
    edges = Counter(round(x * 2) / 2 for _, x, _ in starts)
    edge, n = edges.most_common(1)[0]
    if n / len(starts) < 0.4:
        return []
    by_page: dict[int, list[Box]] = {}
    for page, x, box in starts:
        if 1.5 < abs(x - edge) < 8:
            by_page.setdefault(page, []).append(box)
    return [
        _finding(
            ctx,
            page,
            boxes,
            code="VIS.ALIGNMENT",
            severity="low",
            message=f"{len(boxes)} line(s) on {_label(ctx, page)} start slightly off the text edge.",
            explanation="Lines a few points off the margin look like stray spaces or mismatched indents.",
            recommendation="Remove leading spaces and use the same paragraph indent throughout.",
            expected={"left_edge_pt": edge},
            confidence=0.8,
        )
        for page, boxes in sorted(by_page.items())
    ]
