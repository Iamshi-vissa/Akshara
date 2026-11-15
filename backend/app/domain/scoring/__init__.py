"""Transparent quality scoring (ARCHITECTURE.md §4).

* Each finding belongs to one dimension (by category).
* dimension score = max(0, 100 - sum of severity weights), weights: critical 25, high 10,
  medium 4, low 1, info 0. Findings below full confidence count proportionally.
* overall = mean of the evaluated dimensions.
* Compliance (Phase 4) is scored separately; any failed *hard* rule caps it at 69.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

WEIGHTS = {"critical": 25.0, "high": 10.0, "medium": 4.0, "low": 1.0, "info": 0.0}
DIMENSION_OF_CATEGORY = {
    "structure": "structure",
    "figures_tables": "structure",
    "metadata": "structure",
    "typography": "formatting",
    "page": "formatting",
    "references": "references",
    "layout": "visual",
    "slides": "visual",
    "visual": "visual",
    "content": "content",
}
DIMENSIONS = ("structure", "formatting", "references", "visual")
FORMULA = [
    "dimension = max(0, 100 - sum(weight x confidence)); weights critical 25, high 10, medium 4, low 1, info 0",
    "overall = mean of evaluated dimensions",
]


@dataclass(frozen=True)
class Scored:
    category: str
    severity: str
    confidence: float = 1.0


def score(findings: Iterable[Scored], dimensions: Iterable[str] = DIMENSIONS) -> dict[str, object]:
    dims = list(dimensions)
    penalty = dict.fromkeys(dims, 0.0)
    counts: dict[str, int] = dict.fromkeys(WEIGHTS, 0)
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
        dim = DIMENSION_OF_CATEGORY.get(f.category)
        if dim in penalty:
            penalty[dim] += WEIGHTS[f.severity] * f.confidence
    per_dim = {d: round(max(0.0, 100.0 - p), 1) for d, p in penalty.items()}
    overall = round(sum(per_dim.values()) / len(per_dim), 1) if per_dim else None
    return {"overall": overall, "dimensions": per_dim, "counts": counts, "formula": FORMULA}
