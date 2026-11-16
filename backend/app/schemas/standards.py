from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from app.schemas.common import ApiModel


class StandardVersionOut(ApiModel):
    id: uuid.UUID
    version: str
    status: str
    rule_count: int
    created_at: datetime | None = None
    published_at: datetime | None = None


class StandardOut(ApiModel):
    id: uuid.UUID | None  # None for built-ins
    slug: str
    name: str
    family: str
    description: str
    builtin: bool
    extends: str | None = None
    notice: str | None = None
    versions: list[StandardVersionOut]


class StandardDetail(ApiModel):
    version_id: uuid.UUID
    standard_id: uuid.UUID | None
    slug: str
    name: str
    family: str
    description: str
    builtin: bool
    status: str
    version: str
    extends: str | None
    notice: str | None
    rules: list[dict[str, Any]]  # effective rules (inheritance applied)
    own_rules: list[dict[str, Any]] | None = None  # editable rules of a custom draft


class StandardCreate(ApiModel):
    name: str = Field(min_length=2, max_length=200)
    description: str = Field(default="", max_length=2000)
    extends: str | None = None
    rules: list[dict[str, Any]] = Field(default_factory=list)


class RulesUpdate(ApiModel):
    rules: list[dict[str, Any]]


class ValidationRequest(ApiModel):
    standard_version_id: uuid.UUID
