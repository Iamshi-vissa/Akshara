from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.schemas.common import ApiModel


class FindingOut(ApiModel):
    id: uuid.UUID
    code: str
    category: str
    severity: str
    status: str
    dismiss_reason: str | None
    rule_id: str | None
    constraint_kind: str | None
    node_ids: list[str]
    page_index: int | None
    bbox: list[float] | None
    location: str
    message: str
    explanation: str
    recommendation: str
    expected: Any
    actual: Any
    detector: str
    confidence: float
    fix_available: bool


class InspectionRunOut(ApiModel):
    id: uuid.UUID
    version_id: uuid.UUID
    kind: str
    standard_version_id: uuid.UUID | None
    engine_version: str
    stats: dict[str, Any]
    created_at: datetime


class InspectionWithFindings(InspectionRunOut):
    findings: list[FindingOut]


class FindingUpdate(ApiModel):
    status: Literal["open", "dismissed"]
    reason: str | None = Field(default=None, max_length=500)


class QualityRow(ApiModel):
    document_id: uuid.UUID
    title: str
    kind: str
    version_id: uuid.UUID
    run_id: uuid.UUID
    scores: dict[str, Any]
    total: int
    created_at: datetime
