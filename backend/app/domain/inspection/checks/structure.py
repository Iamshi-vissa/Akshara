from __future__ import annotations

import re

from app.domain.adm.model import Heading, Paragraph
from app.domain.adm.outline import section_role
from app.domain.inspection.checks._util import snippet
from app.domain.inspection.engine import check
from app.domain.inspection.model import Finding, InspectContext


@check("STRUCT.HEADING_LEVEL_SKIP")
def heading_level_skip(ctx: InspectContext) -> list[Finding]:
    out = []
    prev = None
    for h in ctx.adm.headings():
        if h.level == 0:
            continue
        if prev is not None and h.level > prev.level + 1:
            out.append(
                Finding(
                    code="STRUCT.HEADING_LEVEL_SKIP",
                    category="structure",
                    severity="high",
                    message=f"Heading “{snippet(h.text)}” jumps from level {prev.level} to level {h.level}.",
                    explanation="Skipped heading levels break the document outline, navigation panes and "
                    "accessibility tools, and most style guides forbid them.",
                    recommendation=f"Make it a level {prev.level + 1} heading, or add the missing intermediate heading.",
                    node_ids=[h.id],
                    expected=prev.level + 1,
                    actual=h.level,
                    fix_available=True,
                )
            )
        prev = h
    return out


def _parts(label: str) -> list[int] | None:
    if re.fullmatch(r"\d+(\.\d+)*", label):
        return [int(x) for x in label.split(".")]
    return None


@check("STRUCT.HEADING_NUMBERING")
def heading_numbering(ctx: InspectContext) -> list[Finding]:
    """Manually typed numbers ("2.1 Methods") must be unique and consecutive per level."""
    out: list[Finding] = []
    numbered: list[tuple[Heading, list[int]]] = []
    for h in ctx.adm.headings():
        parts = _parts(h.numbering_label) if h.numbering_label and h.level > 0 else None
        if parts is not None:
            numbered.append((h, parts))
    if len(numbered) < 2:
        return out
    last_at_depth: dict[int, list[int]] = {}
    seen: set[tuple[int, ...]] = set()
    for h, parts in numbered:
        depth = len(parts)
        key = tuple(parts)
        problem = None
        if key in seen:
            problem = f"number {'.'.join(map(str, parts))} is used twice"
        else:
            prev = last_at_depth.get(depth)
            parent = last_at_depth.get(depth - 1) if depth > 1 else None
            if depth > 1 and parent is not None and parts[:-1] != parent:
                problem = f"“{'.'.join(map(str, parts))}” does not belong to section {'.'.join(map(str, parent))}"
            elif prev is not None and prev[:-1] == parts[:-1] and parts[-1] != prev[-1] + 1:
                problem = f"numbering jumps from {'.'.join(map(str, prev))} to {'.'.join(map(str, parts))}"
            elif prev is None and depth == 1 and parts[0] != 1:
                problem = f"first section is numbered {parts[0]} instead of 1"
        if problem:
            out.append(
                Finding(
                    code="STRUCT.HEADING_NUMBERING",
                    category="structure",
                    severity="medium",
                    message=f"Heading “{snippet(h.text)}”: {problem}.",
                    explanation="Inconsistent section numbers confuse cross-references and readers.",
                    recommendation="Renumber the headings in order, or use automatic heading numbering.",
                    node_ids=[h.id],
                    actual=h.numbering_label,
                    fix_available=True,
                )
            )
        seen.add(key)
        last_at_depth[depth] = parts
        for d in list(last_at_depth):
            if d > depth:
                del last_at_depth[d]
    return out


@check("STRUCT.MISSING_SECTION")
def missing_sections(ctx: InspectContext) -> list[Finding]:
    """Academic-style documents (with a references section) should have the core sections."""
    roles = {section_role(h.text) for h in ctx.adm.headings()}
    if "references" not in roles or len(ctx.adm.headings()) < 4:
        return []
    out = []
    for role, label, sev in (
        ("abstract", "Abstract", "medium"),
        ("introduction", "Introduction", "medium"),
        ("conclusion", "Conclusion", "medium"),
    ):
        if role not in roles:
            out.append(
                Finding(
                    code="STRUCT.MISSING_SECTION",
                    category="structure",
                    severity=sev,  # type: ignore[arg-type]
                    message=f"No “{label}” section was found.",
                    explanation="Academic and technical reports normally include this section; reviewers look for it.",
                    recommendation=f"Add a “{label}” section, or ignore this if your document type does not need one.",
                    expected=label,
                    actual=None,
                )
            )
    return out


@check("STRUCT.NO_HEADINGS")
def no_headings(ctx: InspectContext) -> list[Finding]:
    if ctx.adm.headings() or ctx.adm.metadata.word_count < 400:
        return []
    return [
        Finding(
            code="STRUCT.NO_HEADINGS",
            category="structure",
            severity="medium",
            message=f"The document has {ctx.adm.metadata.word_count} words but no headings.",
            explanation="Without headings there is no outline, table of contents or navigation.",
            recommendation="Divide the text into sections using heading styles.",
        )
    ]


@check("STRUCT.EMPTY_SECTION")
def empty_sections(ctx: InspectContext) -> list[Finding]:
    out = []
    body = ctx.adm.body
    for i, b in enumerate(body):
        if not isinstance(b, Heading) or b.level == 0:
            continue
        nxt = next((x for x in body[i + 1 :] if not (isinstance(x, Paragraph) and x.role == "empty")), None)
        if nxt is None or (isinstance(nxt, Heading) and nxt.level <= b.level):
            out.append(
                Finding(
                    code="STRUCT.EMPTY_SECTION",
                    category="structure",
                    severity="medium",
                    message=f"Section “{snippet(b.text)}” has no content.",
                    explanation="An empty section is usually unfinished work.",
                    recommendation="Add the section's content or remove the heading.",
                    node_ids=[b.id],
                )
            )
    return out


@check("STRUCT.FAKE_HEADING", formats=("docx",))
def fake_headings(ctx: InspectContext) -> list[Finding]:
    """Short, fully bold body paragraphs that act as headings but are not styled as headings."""
    out = []
    for b in ctx.adm.body:
        if not isinstance(b, Paragraph) or b.role != "body":
            continue
        text = b.text.strip()
        runs = [r for r in b.runs if r.text.strip()]
        if 2 <= len(text) <= 80 and runs and all(r.fmt.bold for r in runs) and not text.endswith((".", ":")):
            out.append(
                Finding(
                    code="STRUCT.FAKE_HEADING",
                    category="structure",
                    severity="low",
                    message=f"“{snippet(text)}” looks like a heading but uses a body text style.",
                    explanation="Manual bold headings are invisible to the outline, numbering and table of contents.",
                    recommendation="Apply a Heading style instead of manual bold formatting.",
                    node_ids=[b.id],
                    fix_available=True,
                )
            )
    return out


@check("META.MISSING", formats=("docx", "pdf", "pptx"))
def metadata(ctx: InspectContext) -> list[Finding]:
    m = ctx.adm.metadata
    missing = [name for name, v in (("title", m.title), ("author", m.authors)) if not v]
    if not missing:
        return []
    return [
        Finding(
            code="META.MISSING",
            category="metadata",
            severity="info",
            message=f"Document properties are missing: {', '.join(missing)}.",
            explanation="Repositories, search engines and screen readers use these properties.",
            recommendation="Fill in the document properties (File → Info → Properties).",
            expected=["title", "author"],
            actual=missing,
        )
    ]
