from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.schemas.common import ApiModel


class DraftCreate(ApiModel):
    kind: str
    title: str = Field(min_length=2, max_length=300)
    topic: str = Field(default="", max_length=2000)
    instructions: str = Field(default="", max_length=4000)
    tone: str = "professional"
    word_target: int | None = Field(default=None, ge=100, le=50000)
    author: str | None = Field(default=None, max_length=200)
    citation_style: Literal["numeric", "author_year"] = "numeric"
    references: list[str] = Field(default_factory=list, max_length=200)
    standard_version_id: uuid.UUID | None = None


class DraftUpdate(ApiModel):
    title: str | None = Field(default=None, max_length=300)
    outline: list[dict[str, Any]] | None = None
    sections: dict[str, str] | None = None
    references: list[str] | None = None
    standard_version_id: uuid.UUID | None = None


class DraftOut(ApiModel):
    id: uuid.UUID
    kind: str
    title: str
    brief: dict[str, Any]
    outline: list[dict[str, Any]]
    sections: dict[str, Any]
    references: list[str]
    standard_version_id: uuid.UUID | None
    status: str
    document_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class KindOut(ApiModel):
    key: str
    label: str
    words: int
    outline: list[dict[str, Any]]


class ExportRequest(ApiModel):
    format: Literal["docx", "pdf", "pptx"]
