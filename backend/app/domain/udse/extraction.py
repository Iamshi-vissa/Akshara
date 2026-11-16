"""Extract candidate rules from guideline text (ARCHITECTURE.md §8.5).

Deterministic pattern extraction only. Every candidate carries the **verbatim sentence** it
came from, and :func:`verify_candidate` re-checks that

1. the quote occurs in the source text (after whitespace normalisation), and
2. every numeric value in the rule also appears in the quote (with unit conversion),

so no value can be invented. Candidates are never applied automatically: a person reviews,
edits and accepts them before they become part of a standard.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_WS = re.compile(r"\s+")
_SENT = re.compile(r"(?<=[.;!?])\s+|\n+")
NUM = r"(\d+(?:\.\d+)?|one|two|three|half|1/2|¾|3/4|½)"
WORDNUM = {"one": 1.0, "two": 2.0, "three": 3.0, "half": 0.5, "1/2": 0.5, "½": 0.5, "3/4": 0.75, "¾": 0.75}
UNITS = {
    "in": "in",
    "inch": "in",
    "inches": "in",
    '"': "in",
    "”": "in",
    "cm": "cm",
    "mm": "mm",
    "pt": "pt",
    "point": "pt",
    "points": "pt",
    "-point": "pt",
}
FONTS = [
    "Times New Roman",
    "Arial",
    "Calibri",
    "Cambria",
    "Georgia",
    "Helvetica",
    "Garamond",
    "Book Antiqua",
    "Verdana",
    "Tahoma",
    "Century Gothic",
    "Courier New",
    "Palatino",
    "Lucida Sans Unicode",
    "Computer Modern",
]


def norm(t: str) -> str:
    return _WS.sub(" ", t).strip()


def _num(tok: str) -> float:
    return WORDNUM.get(tok.lower(), None) or float(tok)


@dataclass
class Candidate:
    rule: dict[str, Any]
    quote: str
    method: str = "pattern"
    evidence_verified: bool = False
    problems: list[str] = field(default_factory=list)


def sentences(text: str) -> list[str]:
    return [norm(s) for s in _SENT.split(text) if len(norm(s)) > 8]


def _rule(
    rid: str,
    title: str,
    category: str,
    selector: dict[str, Any],
    check: dict[str, Any],
    quote: str,
    severity: str = "medium",
    fix: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": rid,
        "title": title,
        "category": category,
        "kind": "hard",
        "severity": severity,
        "selector": selector,
        "check": check,
        "fix": fix or {},
        "provenance": {"source": "Uploaded guideline", "quote": quote, "verification": "extracted"},
    }


def extract(text: str) -> list[Candidate]:
    out: list[Candidate] = []
    seen: set[str] = set()

    def add(c: Candidate) -> None:
        if c.rule["id"] not in seen:
            seen.add(c.rule["id"])
            out.append(c)

    for s in sentences(text):
        low = s.lower()
        # Margins: "1-inch margins on all sides", "margins of 2.5 cm", "left margin 1.5 inches"
        if "margin" in low:
            m = re.search(rf"{NUM}\s*(?:-\s*)?(inch(?:es)?|in\b|cm|mm|\"|”)", low)
            if m:
                value, unit = _num(m.group(1)), UNITS[m.group(2)]
                sides = [x for x in ("top", "bottom", "left", "right") if re.search(rf"\b{x}\b", low)]
                if not sides or re.search(r"all (four )?sides|all margins|each side|every side|margins of", low):
                    sides = sides or ["top", "bottom", "left", "right"]
                for side in sides:
                    add(
                        Candidate(
                            _rule(
                                f"page.margin.{side}",
                                f"{side.capitalize()} margin",
                                "page",
                                {"node": "page_setup"},
                                {
                                    "op": "equals",
                                    "property": f"margins.{side}",
                                    "value": value,
                                    "unit": unit,
                                    "tolerance": 0.05 if unit == "in" else 1,
                                },
                                s,
                                "high",
                                {"strategy": "set_margins", "auto": True},
                            ),
                            s,
                        )
                    )
        # Line spacing
        if re.search(r"double[- ]spac", low):
            add(
                Candidate(
                    _rule(
                        "typography.line_spacing",
                        "Line spacing",
                        "typography",
                        {"node": "body_paragraph"},
                        {"op": "equals", "property": "line_spacing", "value": 2.0, "tolerance": 0.05},
                        s,
                        "high",
                        {"strategy": "set_line_spacing", "auto": True},
                    ),
                    s,
                )
            )
        elif m := re.search(r"(1\.5|one and a half|1\.15)\s*(?:line)?[- ]?spac", low):
            v = 1.5 if m.group(1) in ("1.5", "one and a half") else 1.15
            add(
                Candidate(
                    _rule(
                        "typography.line_spacing",
                        "Line spacing",
                        "typography",
                        {"node": "body_paragraph"},
                        {"op": "equals", "property": "line_spacing", "value": v, "tolerance": 0.05},
                        s,
                        "high",
                        {"strategy": "set_line_spacing", "auto": True},
                    ),
                    s,
                )
            )
        elif re.search(r"single[- ]spac", low):
            add(
                Candidate(
                    _rule(
                        "typography.line_spacing",
                        "Line spacing",
                        "typography",
                        {"node": "body_paragraph"},
                        {"op": "equals", "property": "line_spacing", "value": 1.0, "tolerance": 0.05},
                        s,
                        "high",
                        {"strategy": "set_line_spacing", "auto": True},
                    ),
                    s,
                )
            )
        # Font family and size: "12-point Times New Roman", "Arial, 11 pt"
        fonts = [f for f in FONTS if f.lower() in low]
        if fonts:
            add(
                Candidate(
                    _rule(
                        "typography.body_font",
                        "Body font",
                        "typography",
                        {"node": "body_paragraph"},
                        {"op": "in_set", "property": "font_family", "values": fonts},
                        s,
                        "medium",
                        {"strategy": "set_body_font", "auto": True},
                    ),
                    s,
                )
            )
        size = re.search(r"\b(\d{1,2}(?:\.5)?)\s*(?:-\s*)?(?:pt|point|points)\b", low)
        if size and ("font" in low or fonts or "type" in low or "text" in low):
            add(
                Candidate(
                    _rule(
                        "typography.body_size",
                        "Body font size",
                        "typography",
                        {"node": "body_paragraph"},
                        {
                            "op": "equals",
                            "property": "size_pt",
                            "value": float(size.group(1)),
                            "unit": "pt",
                            "tolerance": 0.25,
                        },
                        s,
                        "medium",
                        {"strategy": "set_body_font", "auto": True},
                    ),
                    s,
                )
            )
        # Paper size
        if re.search(r"\ba4\b", low) and ("paper" in low or "page" in low or "size" in low):
            add(
                Candidate(
                    _rule(
                        "page.paper",
                        "Paper size",
                        "page",
                        {"node": "page_setup"},
                        {"op": "equals", "property": "paper", "value": "A4"},
                        s,
                        "high",
                        {"strategy": "set_paper", "auto": True},
                    ),
                    s,
                )
            )
        elif re.search(r"letter[- ]size|8\.5\s*(?:x|×|by)\s*11", low):  # noqa: RUF001 (guidelines use the multiplication sign)
            add(
                Candidate(
                    _rule(
                        "page.paper",
                        "Paper size",
                        "page",
                        {"node": "page_setup"},
                        {"op": "equals", "property": "paper", "value": "Letter"},
                        s,
                        "high",
                        {"strategy": "set_paper", "auto": True},
                    ),
                    s,
                )
            )
        # Justification
        if re.search(r"\bjustif(y|ied)\b", low) and not re.search(r"\b(not|no|do not|don't)\b[^.]{0,20}justif", low):
            add(
                Candidate(
                    _rule(
                        "typography.alignment",
                        "Text alignment",
                        "typography",
                        {"node": "body_paragraph"},
                        {"op": "equals", "property": "alignment", "value": "justify"},
                        s,
                        "low",
                        {"strategy": "set_alignment", "auto": True},
                    ),
                    s,
                )
            )
        # Page numbers
        if re.search(r"page numbers?|number (all|each|every) pages?|pages? (must|should) be numbered", low):
            add(
                Candidate(
                    _rule(
                        "page.page_numbers",
                        "Page numbers",
                        "page",
                        {"node": "document"},
                        {"op": "equals", "property": "has_page_numbers", "value": True},
                        s,
                        "medium",
                        {"strategy": "add_page_numbers", "auto": True},
                    ),
                    s,
                )
            )
        # Abstract word limit: "abstract ... not exceed 250 words"
        if "abstract" in low:
            m = re.search(r"(\d{2,4})\s*words", low)
            if m:
                add(
                    Candidate(
                        _rule(
                            "structure.abstract_length",
                            "Abstract length",
                            "structure",
                            {"node": "section", "where": {"role": "abstract"}},
                            {"op": "max_words", "max": float(m.group(1))},
                            s,
                            "low",
                        ),
                        s,
                    )
                )
        # Required sections: "must include an abstract, introduction, ..."
        if re.search(r"\b(must|should|shall) (include|contain|have)\b", low):
            for role in ("abstract", "introduction", "methodology", "results", "conclusion", "references"):
                key = {"methodology": "method", "references": "reference"}.get(role, role)
                if key in low:
                    add(
                        Candidate(
                            _rule(
                                f"structure.has_{role}",
                                f"{role.capitalize()} section",
                                "structure",
                                {"node": "heading", "where": {"role": role}},
                                {"op": "present"},
                                s,
                                "high",
                            ),
                            s,
                        )
                    )
    for c in out:
        verify_candidate(c, text)
    return out


def _numbers_in(rule: dict[str, Any]) -> list[tuple[float, str]]:
    chk = rule.get("check", {})
    unit = chk.get("unit", "none")
    vals: list[tuple[float, str]] = []
    for k in ("value", "min", "max"):
        v = chk.get(k)
        if isinstance(v, int | float) and not isinstance(v, bool):
            vals.append((float(v), unit))
    return vals


def verify_candidate(c: Candidate, source_text: str) -> Candidate:
    """Ground the candidate in the source: verbatim quote + every number present in the quote."""
    c.problems = []
    if norm(c.quote).lower() not in norm(source_text).lower():
        c.problems.append("Quote not found verbatim in the source document.")
    quote = norm(c.quote).lower()
    present = {_num(m.group(1)) for m in re.finditer(NUM, quote)}
    if "double" in quote:
        present.add(2.0)
    if "single" in quote:
        present.add(1.0)
    if "one and a half" in quote:
        present.add(1.5)
    for v, _unit in _numbers_in(c.rule):
        if v not in present:
            c.problems.append(f"The value {v:g} does not appear in the quote.")
    c.evidence_verified = not c.problems
    return c
