from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.schemas.common import ApiModel


class ProposalOut(ApiModel):
    id: uuid.UUID
    ordinal: int
    title: str
    rationale: str
    ops: list[dict[str, Any]]
    risk: str
    before: str
    after: str
    node_ids: list[str]
    finding_ids: list[str]
    rule_id: str | None
    origin: str
    decision: str


class ChangeSetOut(ApiModel):
    id: uuid.UUID
    document_id: uuid.UUID
    base_version_id: uuid.UUID
    source: str
    status: str
    summary: dict[str, Any]
    result_version_id: uuid.UUID | None
    error_message: str | None
    created_at: datetime
    applied_at: datetime | None
    proposals: list[ProposalOut] = Field(default_factory=list)


class TextEdit(ApiModel):
    node_id: str
    after: str = Field(max_length=20000)


class ChangeSetCreate(ApiModel):
    source: Literal["autocorrect", "grammar", "ai_edit", "manual"]
    edits: list[TextEdit] = Field(default_factory=list)  # manual
    node_ids: list[str] = Field(default_factory=list)  # grammar / ai_edit
    operation: str | None = None  # ai_edit
    tone: str | None = Field(default=None, max_length=60)


class Decisions(ApiModel):
    decisions: dict[uuid.UUID, Literal["pending", "accepted", "rejected"]]


class RevertRequest(ApiModel):
    version_id: uuid.UUID
