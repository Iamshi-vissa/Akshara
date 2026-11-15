from __future__ import annotations

import re

from app.domain.adm.model import Heading, Paragraph
from app.domain.adm.outline import section_role
from app.domain.inspection.checks._util import snippet
from app.domain.inspection.engine import check
from app.domain.inspection.model import Finding, InspectContext

NUMERIC_LABEL = re.compile(r"^\s*\[(\d+)\]|^\s*(\d+)\.\s")
CITE_GROUP = re.compile(r"\[(\d+(?:\s*[-–,]\s*\d+)*)\]")  # noqa: RUF001


def cited_numbers(text: str) -> set[int]:
    nums: set[int] = set()
    for group in CITE_GROUP.findall(text):
        for part in re.split(r"\s*,\s*", group):
            m = re.match(r"(\d+)\s*[-–]\s*(\d+)", part)  # noqa: RUF001
            if m:
                a, b = int(m.group(1)), int(m.group(2))
                if 0 < b - a < 50:
                    nums.update(range(a, b + 1))
            elif part.strip().isdigit():
                nums.add(int(part))
    return nums


def reference_entries(ctx: InspectContext) -> list[Paragraph]:
    return [b for b in ctx.adm.body if isinstance(b, Paragraph) and b.role == "reference_entry" and b.text.strip()]


def _body_text(ctx: InspectContext) -> str:
    return " ".join(b.text for b in ctx.adm.body if isinstance(b, Paragraph) and b.role != "reference_entry")


def _label(p: Paragraph) -> int | None:
    m = NUMERIC_LABEL.match(p.text)
    return int(m.group(1) or m.group(2)) if m else None


@check("REF.ORDER")
def ref_order(ctx: InspectContext) -> list[Finding]:
    entries = reference_entries(ctx)
    labels = [(_label(e), e) for e in entries]
    numeric = [(n, e) for n, e in labels if n is not None]
    if len(numeric) < 2 or len(numeric) < len(entries) * 0.8:
        return []
    out = []
    for i, (n, e) in enumerate(numeric):
        if n != i + 1:
            out.append(
                Finding(
                    code="REF.ORDER",
                    category="references",
                    severity="low",
                    message=f"Reference [{n}] is in position {i + 1} of the list.",
                    explanation="Numbered reference lists must be in numeric order so readers can find entries.",
                    recommendation="Sort the references by number (or renumber them in order of first citation).",
                    node_ids=[e.id],
                    expected=i + 1,
                    actual=n,
                    fix_available=True,
                )
            )
            break  # one finding is enough to flag the list
    return out


@check("REF.UNCITED")
def uncited(ctx: InspectContext) -> list[Finding]:
    entries = reference_entries(ctx)
    if not entries:
        return []
    body = _body_text(ctx)
    cited = cited_numbers(body)
    out = []
    for e in entries:
        n = _label(e)
        if n is not None:
            is_cited = n in cited
        else:
            m = re.match(r"\s*([A-Z][A-Za-z'\-]+)", e.text)
            year = re.search(r"\b(19|20)\d{2}[a-z]?\b", e.text)
            is_cited = bool(m and year and re.search(rf"{re.escape(m.group(1))}[^.]{{0,60}}{year.group(0)}", body))
        if not is_cited:
            out.append(
                Finding(
                    code="REF.UNCITED",
                    category="references",
                    severity="low",
                    message=f"Reference “{snippet(e.text, 50)}” is never cited in the text.",
                    explanation="Most styles require every listed reference to be cited.",
                    recommendation="Cite it where it is used, or remove it from the list.",
                    node_ids=[e.id],
                )
            )
    return out


@check("REF.CITATION_WITHOUT_ENTRY")
def citation_without_entry(ctx: InspectContext) -> list[Finding]:
    entries = reference_entries(ctx)
    cited = cited_numbers(_body_text(ctx))
    if not cited:
        return []
    has_section = any(isinstance(h, Heading) and section_role(h.text) == "references" for h in ctx.adm.headings())
    if not has_section:
        return [
            Finding(
                code="REF.MISSING_SECTION",
                category="references",
                severity="high",
                message=f"The text cites {len(cited)} sources but there is no references section.",
                explanation="Citations must point to entries in a reference list.",
                recommendation="Add a “References” section listing every cited source.",
            )
        ]
    labels = {n for n in (_label(e) for e in entries) if n is not None}
    if not labels:
        return []
    missing = sorted(cited - labels)
    if not missing:
        return []
    return [
        Finding(
            code="REF.CITATION_WITHOUT_ENTRY",
            category="references",
            severity="high",
            message=f"Cited but not listed: {', '.join(f'[{n}]' for n in missing[:10])}.",
            explanation="A citation without a matching reference cannot be verified.",
            recommendation="Add the missing references, or correct the citation numbers.",
            actual=missing,
        )
    ]


@check("REF.DOI_FORMAT")
def doi_format(ctx: InspectContext) -> list[Finding]:
    entries = reference_entries(ctx)
    styles = set()
    for e in entries:
        if re.search(r"https?://(dx\.)?doi\.org/10\.", e.text):
            styles.add("url")
        elif re.search(r"\bdoi:\s*10\.", e.text, re.IGNORECASE):
            styles.add("prefix")
    if len(styles) < 2:
        return []
    return [
        Finding(
            code="REF.DOI_FORMAT",
            category="references",
            severity="low",
            message="DOIs are written in different formats (both “doi:” and https://doi.org/ links).",
            explanation="Current styles (APA 7, IEEE) recommend DOIs as https://doi.org/ links.",
            recommendation="Write every DOI as https://doi.org/10.xxxx/...",
            fix_available=True,
        )
    ]
