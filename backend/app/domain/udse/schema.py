"""UDSE rule schema (ARCHITECTURE.md §8). Rules are data; the engine is deterministic code.

Hard rules are checked only by deterministic operators. Soft rules may use ``llm_assess``,
which runs only when a language model is configured and never affects the hard-rule cap.
An LLM may *evaluate* a soft rule; it may never *create* a rule (extraction requires a
verbatim source quote and human review — see ``extraction.py``).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Unit = Literal["pt", "in", "mm", "cm", "none"]
Op = Literal[
    "equals",
    "not_equals",
    "in_set",
    "in_range",
    "matches",
    "present",
    "absent",
    "count",
    "max_words",
    "min_words",
    "order",
    "consistent",
    "all_have",
    "sequence",
    "referenced_in_text",
    "citation_style",
    "reference_order",
    "llm_assess",
]
Target = Literal[
    "document",
    "page_setup",
    "body_paragraph",
    "paragraph",
    "heading",
    "caption",
    "figure",
    "table",
    "reference_entry",
    "section",
    "slide",
    "shape",
]
RuleCategory = Literal["page", "typography", "structure", "references", "figures_tables", "layout", "slides"]
DocFormat = Literal["docx", "pdf", "pptx"]


def _text_formats() -> list[DocFormat]:
    return ["docx", "pdf"]


DETERMINISTIC_OPS: frozenset[str] = frozenset(Op.__args__) - {"llm_assess"}  # type: ignore[attr-defined]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Selector(_M):
    node: Target
    where: dict[str, Any] = Field(default_factory=dict)  # e.g. {"level": 1}, {"role": "abstract"}


class CheckSpec(_M):
    op: Op
    property: str | None = None
    value: Any = None
    values: list[Any] | None = None
    min: float | None = None
    max: float | None = None
    unit: Unit = "none"
    tolerance: float = 0.0  # in the rule's unit
    case_insensitive: bool = True
    pattern: str | None = None
    rubric: str | None = None  # llm_assess only, must come from the standard


class Fix(_M):
    strategy: str | None = None  # maps to a correction fixer (Phase 5)
    auto: bool = False
    hint: str | None = None


class Provenance(_M):
    source: str  # human-readable source title
    locator: str | None = None  # section / page in the source
    url: str | None = None
    quote: str | None = None  # verbatim text from the source (required for extracted rules)
    verification: Literal["primary", "secondary", "unverified", "user", "extracted"] = "unverified"
    notes: str | None = None


class Rule(_M):
    id: str = Field(pattern=r"^[a-z0-9_.\-]{2,96}$")
    title: str = Field(min_length=2, max_length=200)
    category: RuleCategory
    kind: Literal["hard", "soft"]
    severity: Literal["critical", "high", "medium", "low", "info"]
    applies_to: list[DocFormat] = Field(default_factory=_text_formats)
    selector: Selector
    check: CheckSpec
    message: str | None = None  # may use {actual} and {expected}
    fix: Fix = Field(default_factory=Fix)
    provenance: Provenance | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def _hard_rules_are_deterministic(self) -> Rule:
        if self.kind == "hard" and self.check.op not in DETERMINISTIC_OPS:
            raise ValueError("hard rules must use a deterministic operator (llm_assess is soft-only)")
        if self.check.op == "llm_assess" and not self.check.rubric:
            raise ValueError("llm_assess needs a rubric taken from the standard")
        return self


class StandardProfile(_M):
    slug: str = Field(pattern=r"^[a-z0-9\-]{2,64}$")
    name: str
    version: str = "1.0.0"
    family: Literal["ieee", "apa", "mla", "institutional", "corporate", "custom"]
    description: str = ""
    extends: str | None = None  # slug of a built-in profile
    applies_to: list[DocFormat] = Field(default_factory=_text_formats)
    notice: str | None = None
    rules: list[Rule]

    @model_validator(mode="after")
    def _unique_ids(self) -> StandardProfile:
        ids = [r.id for r in self.rules]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate rule ids: {sorted(dupes)}")
        return self


def merge(base: StandardProfile, child: StandardProfile) -> StandardProfile:
    """Child rules override base rules with the same id; new ids are appended."""
    rules = {r.id: r for r in base.rules}
    for r in child.rules:
        rules[r.id] = r
    return child.model_copy(update={"rules": list(rules.values())})
