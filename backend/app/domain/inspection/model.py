from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.domain.adm.model import AdmDocument

Severity = Literal["critical", "high", "medium", "low", "info"]
SEVERITY_ORDER: dict[str, int] = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
Category = Literal[
    "structure",
    "typography",
    "page",
    "references",
    "figures_tables",
    "layout",
    "metadata",
    "slides",
    "content",
    "visual",
]


@dataclass
class Finding:
    code: str
    category: Category
    severity: Severity
    message: str  # what is wrong
    explanation: str  # why it matters
    recommendation: str  # how to fix it
    node_ids: list[str] = field(default_factory=list)
    page: int | None = None  # 0-based rendered page/slide
    bbox: tuple[float, float, float, float] | None = None
    location: str = ""
    expected: Any = None
    actual: Any = None
    detector: Literal["deterministic", "visual", "llm"] = "deterministic"
    confidence: float = 1.0
    fix_available: bool = False
    rule_id: str | None = None
    constraint: Literal["hard", "soft"] | None = None


@dataclass
class InspectContext:
    adm: AdmDocument
    layout: dict[str, Any] | None = None  # rendered geometry (Phase 2 render job)

    @property
    def exact(self) -> bool:
        return self.adm.source_format in ("docx", "pptx", "generated")

    @property
    def confidence(self) -> float:
        """Findings derived from inferred (PDF) structure carry lower confidence."""
        return 1.0 if self.exact else 0.7
