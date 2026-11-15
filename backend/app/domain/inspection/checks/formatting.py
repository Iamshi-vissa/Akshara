from __future__ import annotations

from collections import defaultdict

from app.domain.adm.model import Heading, Paragraph
from app.domain.inspection.checks._util import body_paragraphs, dominant, snippet
from app.domain.inspection.engine import NotEvaluated, check
from app.domain.inspection.model import Finding, InspectContext


def _font_key(p: Paragraph | Heading) -> tuple[str | None, float | None]:
    f = p.dominant_run_fmt()
    return (f.font_family, f.size_pt)


@check("FMT.FONT_INCONSISTENT")
def body_font(ctx: InspectContext) -> list[Finding]:
    paras = body_paragraphs(ctx.adm)
    if len(paras) < 3:
        raise NotEvaluated("Too little body text to judge font consistency.")
    weighted = [(_font_key(p), len(p.text)) for p in paras]
    main, share = dominant(weighted)
    if main is None or share < 0.6:
        raise NotEvaluated("No dominant body font (several fonts are used equally).")
    out = []
    for p in paras:
        key = _font_key(p)
        family_differs = key[0] and main[0] and key[0] != main[0]
        size_differs = key[1] and main[1] and abs(key[1] - main[1]) >= 0.5
        if family_differs or size_differs:
            out.append(
                Finding(
                    code="FMT.FONT_INCONSISTENT",
                    category="typography",
                    severity="medium",
                    message=f"Paragraph “{snippet(p.text, 50)}” uses {key[0]} {key[1]} pt; the body text uses {main[0]} {main[1]} pt.",
                    explanation="Mixed fonts in running text look unprofessional and usually come from pasted content.",
                    recommendation=f"Set this paragraph to {main[0]} {main[1]} pt (or clear direct formatting).",
                    node_ids=[p.id],
                    expected={"font_family": main[0], "size_pt": main[1]},
                    actual={"font_family": key[0], "size_pt": key[1]},
                    fix_available=True,
                )
            )
    return out


@check("FMT.HEADING_INCONSISTENT")
def heading_consistency(ctx: InspectContext) -> list[Finding]:
    by_level: dict[int, list[Heading]] = defaultdict(list)
    for h in ctx.adm.headings():
        if h.level > 0:
            by_level[h.level].append(h)
    out = []
    for level, heads in by_level.items():
        if len(heads) < 2:
            continue
        main, share = dominant((_font_key(h), 1) for h in heads)
        if main is None or share <= 0.5:
            continue
        for h in heads:
            key = _font_key(h)
            if key != main and all(v is not None for v in key):
                out.append(
                    Finding(
                        code="FMT.HEADING_INCONSISTENT",
                        category="typography",
                        severity="medium",
                        message=f"Level-{level} heading “{snippet(h.text)}” is {key[0]} {key[1]} pt; other level-{level} headings are {main[0]} {main[1]} pt.",
                        explanation="Headings of the same level should look identical so readers can see the hierarchy.",
                        recommendation=f"Reapply the Heading {level} style (or format it as {main[0]} {main[1]} pt).",
                        node_ids=[h.id],
                        expected={"font_family": main[0], "size_pt": main[1]},
                        actual={"font_family": key[0], "size_pt": key[1]},
                        fix_available=True,
                    )
                )
    return out


@check("FMT.SPACING_INCONSISTENT", formats=("docx", "generated"))
def line_spacing(ctx: InspectContext) -> list[Finding]:
    paras = body_paragraphs(ctx.adm)
    if len(paras) < 3:
        raise NotEvaluated("Too little body text to judge spacing.")
    main, share = dominant((p.fmt.line_spacing, len(p.text)) for p in paras)
    if main is None or share < 0.6:
        return []
    out = []
    for p in paras:
        if p.fmt.line_spacing is not None and abs(p.fmt.line_spacing - main) >= 0.15:
            out.append(
                Finding(
                    code="FMT.SPACING_INCONSISTENT",
                    category="typography",
                    severity="low",
                    message=f"Paragraph “{snippet(p.text, 50)}” has line spacing {p.fmt.line_spacing:g}; the body uses {main:g}.",
                    explanation="Uneven line spacing makes pages look patchy and can break page-count limits.",
                    recommendation=f"Set line spacing to {main:g}.",
                    node_ids=[p.id],
                    expected=main,
                    actual=p.fmt.line_spacing,
                    fix_available=True,
                )
            )
    return out


@check("FMT.ALIGNMENT_INCONSISTENT", formats=("docx", "generated"))
def alignment(ctx: InspectContext) -> list[Finding]:
    paras = body_paragraphs(ctx.adm)
    main, share = dominant((p.fmt.alignment, len(p.text)) for p in paras)
    if main is None or share < 0.8 or len(paras) < 4:
        return []
    return [
        Finding(
            code="FMT.ALIGNMENT_INCONSISTENT",
            category="typography",
            severity="low",
            message=f"Paragraph “{snippet(p.text, 50)}” is {p.fmt.alignment}-aligned; body text is {main}-aligned.",
            explanation="Alignment should be uniform across running text.",
            recommendation=f"Set the alignment to {main}.",
            node_ids=[p.id],
            expected=main,
            actual=p.fmt.alignment,
            fix_available=True,
        )
        for p in paras
        if p.fmt.alignment and p.fmt.alignment != main
    ]


@check("LAYOUT.EMPTY_PARAGRAPHS", formats=("docx", "generated"))
def empty_paragraphs(ctx: InspectContext) -> list[Finding]:
    out = []
    run: list[Paragraph] = []
    for b in [*ctx.adm.body, None]:
        if isinstance(b, Paragraph) and b.role == "empty":
            run.append(b)
            continue
        if len(run) >= 2:
            out.append(
                Finding(
                    code="LAYOUT.EMPTY_PARAGRAPHS",
                    category="layout",
                    severity="low",
                    message=f"{len(run)} empty paragraphs in a row are used as spacing.",
                    explanation="Blank paragraphs shift unpredictably when text changes and create half-empty pages.",
                    recommendation="Delete them and use paragraph spacing or a page break instead.",
                    node_ids=[x.id for x in run],
                    actual=len(run),
                    fix_available=True,
                )
            )
        run = []
    return out
