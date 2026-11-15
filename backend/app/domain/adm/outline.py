"""Derived structure: section tree, section roles and summary counts (pure functions)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.domain.adm.model import AdmDocument, Caption, Figure, Heading, Paragraph, Table

SECTION_ROLES: dict[str, tuple[str, ...]] = {
    "abstract": ("abstract", "summary", "executive summary"),
    "keywords": ("keywords", "index terms", "key words"),
    "introduction": ("introduction", "background", "overview"),
    "related_work": ("related work", "literature review", "prior work"),
    "methodology": (
        "methodology",
        "methods",
        "method",
        "materials and methods",
        "approach",
        "proposed method",
        "proposed system",
        "system design",
        "experimental setup",
    ),
    "results": ("results", "experiments", "evaluation", "findings", "results and discussion"),
    "discussion": ("discussion",),
    "conclusion": (
        "conclusion",
        "conclusions",
        "conclusion and future work",
        "future work",
        "concluding remarks",
    ),
    "references": ("references", "bibliography", "works cited", "reference", "literature cited"),
    "appendix": ("appendix", "appendices"),
    "acknowledgements": (
        "acknowledgement",
        "acknowledgements",
        "acknowledgment",
        "acknowledgments",
    ),
}

_NUMBER_PREFIX = re.compile(
    r"^\s*(?:(?:\d+(?:\.\d+)*\.?)|(?:[IVXLC]+\.)|(?:[A-Z]\.)|(?:appendix\s+[A-Z0-9]+[.:]?))\s*",
    re.IGNORECASE,
)


def strip_numbering(text: str) -> str:
    return _NUMBER_PREFIX.sub("", text).strip().rstrip(":.").strip()


def section_role(heading_text: str) -> str:
    if re.match(r"^\s*(appendix|appendices)\b", heading_text, re.IGNORECASE):
        return "appendix"
    t = strip_numbering(heading_text).lower()
    for role, names in SECTION_ROLES.items():
        if t in names or any(t.startswith(n + " ") for n in names if role == "appendix"):
            return role
    return "unknown"


@dataclass
class OutlineNode:
    id: str
    text: str
    level: int
    role: str
    children: list[OutlineNode] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "text": self.text,
            "level": self.level,
            "role": self.role,
            "children": [c.as_dict() for c in self.children],
        }


def outline(doc: AdmDocument) -> list[OutlineNode]:
    if doc.slides:
        return [OutlineNode(id=s.id, text=s.title or f"Slide {s.index + 1}", level=1, role="slide") for s in doc.slides]
    roots: list[OutlineNode] = []
    stack: list[OutlineNode] = []
    for h in doc.headings():
        node = OutlineNode(id=h.id, text=h.text.strip(), level=h.level, role=section_role(h.text))
        while stack and stack[-1].level >= h.level:
            stack.pop()
        (stack[-1].children if stack else roots).append(node)
        stack.append(node)
    return roots


def summary(doc: AdmDocument) -> dict[str, object]:
    body = doc.body
    roles = sorted({section_role(h.text) for h in doc.headings()} - {"unknown"})
    return {
        "analysis": "complete",
        "adm_schema_version": doc.adm_schema_version,
        "pages": doc.metadata.page_count,
        "slides": len(doc.slides) or None,
        "words": doc.metadata.word_count,
        "headings": sum(isinstance(b, Heading) for b in body),
        "paragraphs": sum(isinstance(b, Paragraph) and b.role != "empty" for b in body),
        "tables": sum(isinstance(b, Table) for b in body),
        "figures": sum(isinstance(b, Figure) for b in body),
        "captions": sum(isinstance(b, Caption) for b in body),
        "references": sum(isinstance(b, Paragraph) and b.role == "reference_entry" for b in body),
        "sections_found": roles,
        "warnings": doc.warnings,
    }


def count_words(text: str) -> int:
    return len(re.findall(r"\w+", text))
