from __future__ import annotations

import re

from app.domain.adm.model import Caption, Figure, Table
from app.domain.inspection.checks._util import label_number
from app.domain.inspection.engine import check
from app.domain.inspection.model import Finding, InspectContext


def _pdf_has_nearby_caption(ctx: InspectContext, node: Figure | Table) -> bool:
    if node.source.page is None or node.source.bbox is None:
        return False
    _, y0, _, y1 = node.source.bbox
    for c in ctx.adm.body:
        if isinstance(c, Caption) and c.source.page == node.source.page and c.source.bbox:
            cy0, cy1 = c.source.bbox[1], c.source.bbox[3]
            if -10 <= cy0 - y1 <= 80 or -10 <= y0 - cy1 <= 80:
                return True
    return False


@check("FIG.MISSING_CAPTION")
def missing_captions(ctx: InspectContext) -> list[Finding]:
    out = []
    for b in ctx.adm.body:
        if not isinstance(b, Figure | Table):
            continue
        has = b.caption_id is not None or (ctx.adm.source_format == "pdf" and _pdf_has_nearby_caption(ctx, b))
        if isinstance(b, Figure) and ctx.adm.source_format == "pdf" and (b.width_pt or 0) < 60:
            continue  # tiny images (logos, icons) are not figures
        if not has:
            kind = "Figure" if isinstance(b, Figure) else "Table"
            out.append(
                Finding(
                    code="FIG.MISSING_CAPTION" if kind == "Figure" else "TBL.MISSING_CAPTION",
                    category="figures_tables",
                    severity="high",
                    message=f"A {kind.lower()} has no caption.",
                    explanation=f"Every {kind.lower()} needs a numbered caption so the text can refer to it.",
                    recommendation=f"Add a caption such as “{kind} N. Description” {'below' if kind == 'Figure' else 'above'} it.",
                    node_ids=[b.id],
                    fix_available=False,
                )
            )
    return out


def _sequence_findings(ctx: InspectContext, caps: list[Caption], kind: str) -> list[Finding]:
    out = []
    expected = 1
    seen: set[int] = set()
    for c in caps:
        n = label_number(c.number)
        if n is None:
            continue
        if n in seen:
            problem = f"{kind} {c.number} is numbered twice"
        elif n != expected:
            problem = f"expected {kind} {expected}, found {kind} {c.number}"
        else:
            problem = None
        if problem:
            out.append(
                Finding(
                    code="FIG.NUMBERING" if kind == "Figure" else "TBL.NUMBERING",
                    category="figures_tables",
                    severity="medium",
                    message=f"Caption numbering: {problem}.",
                    explanation="Gaps or duplicates in numbering break cross-references.",
                    recommendation=f"Renumber {kind.lower()}s consecutively (or use automatic caption numbering).",
                    node_ids=[c.id],
                    expected=expected,
                    actual=c.number,
                    fix_available=True,
                )
            )
        seen.add(n)
        expected = max(expected, n) + 1
    return out


@check("FIG.NUMBERING")
def numbering(ctx: InspectContext) -> list[Finding]:
    caps = [b for b in ctx.adm.body if isinstance(b, Caption)]
    return _sequence_findings(ctx, [c for c in caps if c.target_kind == "figure"], "Figure") + _sequence_findings(
        ctx, [c for c in caps if c.target_kind == "table"], "Table"
    )


@check("FIG.NOT_REFERENCED")
def not_referenced(ctx: InspectContext) -> list[Finding]:
    text_nodes = [b for b in ctx.adm.body if b.type in ("paragraph",)]
    body_text = " ".join(b.text for b in text_nodes)
    out = []
    for c in (b for b in ctx.adm.body if isinstance(b, Caption) and b.number):
        if c.target_kind == "figure":
            pat = rf"\b(fig\.?|figure)\s*{re.escape(c.number or '')}\b"
            code, kind = "FIG.NOT_REFERENCED", "Figure"
        elif c.target_kind == "table":
            pat = rf"\btable\s*{re.escape(c.number or '')}\b"
            code, kind = "TBL.NOT_REFERENCED", "Table"
        else:
            continue
        if not re.search(pat, body_text, re.IGNORECASE):
            out.append(
                Finding(
                    code=code,
                    category="figures_tables",
                    severity="low",
                    message=f"{kind} {c.number} is never mentioned in the text.",
                    explanation=f"Each {kind.lower()} should be introduced in the text before or near where it appears.",
                    recommendation=f"Refer to it in the text, e.g. “as shown in {kind} {c.number}”.",
                    node_ids=[c.id],
                )
            )
    return out


@check("TBL.BROKEN", formats=("docx", "generated"))
def broken_tables(ctx: InspectContext) -> list[Finding]:
    out = []
    for t in (b for b in ctx.adm.body if isinstance(b, Table)):
        widths = {sum(c.col_span for c in row) for row in t.rows}
        empty = all(not c.text for row in t.rows for c in row)
        if len(widths) > 1 or empty or not t.rows:
            out.append(
                Finding(
                    code="TBL.BROKEN",
                    category="figures_tables",
                    severity="medium",
                    message="Table has "
                    + ("no content." if empty or not t.rows else "rows with different numbers of columns."),
                    explanation="Ragged or empty tables usually come from broken copy-paste and render unpredictably.",
                    recommendation="Rebuild the table with a regular grid.",
                    node_ids=[t.id],
                    actual=sorted(widths),
                )
            )
    return out
