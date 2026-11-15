from __future__ import annotations

from app.domain.inspection.engine import NotEvaluated, check
from app.domain.inspection.model import Finding, InspectContext


@check("PAGE.NO_PAGE_NUMBERS", formats=("docx", "pdf"))
def page_numbers(ctx: InspectContext) -> list[Finding]:
    setups = ctx.adm.page_setups
    if not setups:
        raise NotEvaluated("No page setup information.")
    pages = ctx.adm.metadata.page_count or (len((ctx.layout or {}).get("pages", [])) or None)
    if pages is not None and pages < 2:
        return []
    has = any(hf.has_page_number for s in setups for hf in [*s.headers, *s.footers])
    if has:
        return []
    return [
        Finding(
            code="PAGE.NO_PAGE_NUMBERS",
            category="page",
            severity="medium",
            message="Pages are not numbered.",
            explanation="Multi-page documents need page numbers for reviewing and citing.",
            recommendation="Insert a page-number field in the header or footer.",
            fix_available=ctx.adm.source_format == "docx",
        )
    ]


@check("PAGE.MARGINS_INCONSISTENT", formats=("docx",))
def margins(ctx: InspectContext) -> list[Finding]:
    sets = [(s.id, s.margins) for s in ctx.adm.page_setups if s.margins]
    distinct = {(m.top, m.bottom, m.left, m.right) for _, m in sets}
    if len(distinct) <= 1:
        return []
    desc = "; ".join(
        f"section {i + 1}: {m.top:g}/{m.bottom:g}/{m.left:g}/{m.right:g} pt" for i, (_, m) in enumerate(sets)
    )
    return [
        Finding(
            code="PAGE.MARGINS_INCONSISTENT",
            category="page",
            severity="medium",
            message="Sections use different margins (top/bottom/left/right).",
            explanation="Changing margins between sections shifts the text block and is rarely intended.",
            recommendation="Use the same margins in every section.",
            actual=desc,
            fix_available=True,
        )
    ]


@check("PAGE.SIZE_INCONSISTENT", formats=("docx", "pdf"))
def paper(ctx: InspectContext) -> list[Finding]:
    sizes = {(s.paper, s.orientation) for s in ctx.adm.page_setups}
    if len({p for p, _ in sizes}) <= 1:
        return []
    return [
        Finding(
            code="PAGE.SIZE_INCONSISTENT",
            category="page",
            severity="medium",
            message="The document mixes paper sizes: " + ", ".join(sorted(p for p, _ in sizes)) + ".",
            explanation="Mixed paper sizes cause printing problems and usually indicate merged files.",
            recommendation="Use a single paper size for the whole document.",
            actual=sorted(p for p, _ in sizes),
            fix_available=ctx.adm.source_format == "docx",
        )
    ]
