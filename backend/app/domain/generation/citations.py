"""Citation safety for generated text (ARCHITECTURE.md §9 Phase 6, rule: never fabricate sources).

Generated text may cite only the references the user supplied, as [n] markers. Anything that
looks like a citation but does not point at a supplied reference is replaced with a visible
"[citation needed]" so a person can resolve it — it is never silently kept.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

BRACKET = re.compile(r"\[(\d+(?:\s*[-–,]\s*\d+)*)\]")  # noqa: RUF001
AUTHOR_YEAR = re.compile(r"\((?:[A-Z][A-Za-z'\-]+(?: et al\.)?(?:,| and| &)[^()]{0,60}?(?:19|20)\d{2}[a-z]?)\)")
DOI = re.compile(r"\b(?:doi:\s*|https?://(?:dx\.)?doi\.org/)10\.\d{4,9}/\S+", re.IGNORECASE)
URL = re.compile(r"https?://\S+")
NEEDED = "[citation needed]"


@dataclass
class CitationReport:
    kept: list[int] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)


def _numbers(group: str) -> list[int]:
    out: list[int] = []
    for part in re.split(r"\s*,\s*", group):
        m = re.match(r"(\d+)\s*[-–]\s*(\d+)", part)  # noqa: RUF001
        if m:
            out.extend(range(int(m.group(1)), int(m.group(2)) + 1))
        elif part.strip().isdigit():
            out.append(int(part))
    return out


def sanitize(text: str, allowed: int, allow_urls: frozenset[str] = frozenset()) -> tuple[str, CitationReport]:
    """Keep [n] only for 1..allowed; replace invented citations, DOIs and URLs with [citation needed]."""
    rep = CitationReport()

    def bracket(m: re.Match[str]) -> str:
        nums = _numbers(m.group(1))
        if nums and all(1 <= n <= allowed for n in nums):
            rep.kept.extend(nums)
            return m.group(0)
        rep.removed.append(m.group(0))
        return NEEDED

    def other(m: re.Match[str]) -> str:
        if m.group(0).rstrip(".,;)") in allow_urls:
            return m.group(0)
        rep.removed.append(m.group(0))
        return NEEDED

    text = BRACKET.sub(bracket, text)
    text = AUTHOR_YEAR.sub(other, text)
    text = DOI.sub(other, text)
    text = URL.sub(other, text)
    return re.sub(r"(\[citation needed\]\s*){2,}", NEEDED + " ", text), rep
