from __future__ import annotations

import uuid
from typing import Literal

from pydantic import Field, model_validator

from app.schemas.common import ApiModel


class PresentationCreate(ApiModel):
    source: Literal["document", "outline", "brief"]
    theme: str = "paper"
    title: str = Field(default="", max_length=300)
    version_id: uuid.UUID | None = None
    outline: str = Field(default="", max_length=50_000)
    brief: str = Field(default="", max_length=8000)
    audience: str = Field(default="", max_length=500)
    slide_count: int = Field(default=10, ge=3, le=30)

    @model_validator(mode="after")
    def _source_fields(self) -> PresentationCreate:
        if self.source == "document" and self.version_id is None:
            raise ValueError("version_id is required when source is 'document'.")
        if self.source == "outline" and not self.outline.strip():
            raise ValueError("outline is required when source is 'outline'.")
        if self.source == "brief" and len(self.brief.strip()) < 20:
            raise ValueError("brief must be at least 20 characters when source is 'brief'.")
        return self


class ThemeOut(ApiModel):
    key: str
    label: str
    background: str
    title: str
    accent: str
