"""Compare a reference as written with a registry record."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from app.domain.references.model import Parsed, Record
from app.domain.references.parse import normalise_title


def title_similarity(a: str, b: str) -> float:
    na, nb = normalise_title(a), normalise_title(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    short, long_ = sorted((na, nb), key=len)
    # "Title" vs "Title: Subtitle" (registries split subtitles), or one is nearly all of the other.
    # A short generic title inside a longer one ("Notes" in "Notes on writing") is not a match.
    if long_.startswith(short) and len(short.split()) >= 3 and len(short) / len(long_) >= 0.35:
        return 0.95
    if short in long_ and len(short) / len(long_) >= 0.8:
        return 0.95
    ta, tb = set(na.split()), set(nb.split())
    jacc = len(ta & tb) / len(ta | tb)
    return max(jacc, SequenceMatcher(None, na, nb).ratio())


@dataclass
class Comparison:
    title: float
    year_ok: bool | None  # None: the reference gives no year
    author_ok: bool | None  # None: no authors could be read
    differences: list[str]

    @property
    def score(self) -> float:
        s = self.title
        if self.year_ok is False:
            s -= 0.15
        if self.author_ok is False:
            s -= 0.2
        return s


def compare(p: Parsed, r: Record) -> Comparison:
    diffs: list[str] = []
    t = title_similarity(p.title, r.title) if p.title else 0.0
    if p.title and t < 0.85:
        diffs.append(f'title: written "{p.title}", registry "{r.title}"')
    year_ok = None
    if p.year is not None and r.year is not None:
        year_ok = abs(p.year - r.year) <= 1  # online-first vs. print year often differ by one
        if not year_ok:
            diffs.append(f"year: written {p.year}, registry {r.year}")
    author_ok = None
    if p.authors and r.authors:
        first = normalise_title(p.authors[0])
        families = [normalise_title(a.family) for a in r.authors]
        author_ok = any(first and (first == f or first in f.split()) for f in families)
        if not author_ok:
            diffs.append(f"first author: written {p.authors[0]}, registry {r.authors[0].family}")
    return Comparison(title=t, year_ok=year_ok, author_ok=author_ok, differences=diffs)
