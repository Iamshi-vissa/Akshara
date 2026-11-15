from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

from app.domain.adm.model import AdmDocument, Paragraph


def body_paragraphs(adm: AdmDocument) -> list[Paragraph]:
    """Running text: excludes empty, title, list, reference and table-of-contents paragraphs."""
    return [b for b in adm.body if isinstance(b, Paragraph) and b.role == "body" and len(b.text.strip()) >= 20]


def dominant[T](values: Iterable[tuple[T, int]]) -> tuple[T | None, float]:
    """Weighted mode and its share of the total weight."""
    c: Counter[T] = Counter()
    for v, w in values:
        if v is not None:
            c[v] += w
    if not c:
        return None, 0.0
    v, n = c.most_common(1)[0]
    return v, n / sum(c.values())


def roman_to_int(s: str) -> int | None:
    vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
    s = s.upper()
    if not s or any(ch not in vals for ch in s):
        return None
    total = 0
    for i, ch in enumerate(s):
        v = vals[ch]
        total += -v if i + 1 < len(s) and vals[s[i + 1]] > v else v
    return total


def label_number(num: str | None) -> int | None:
    if num is None:
        return None
    m = re.match(r"^(\d+)", num)
    if m:
        return int(m.group(1))
    return roman_to_int(num)


def snippet(text: str, n: int = 60) -> str:
    t = " ".join(text.split())
    return t if len(t) <= n else t[: n - 1] + "…"
