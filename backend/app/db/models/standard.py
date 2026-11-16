from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk


class Standard(UUIDPk, Timestamps, Base):
    """A user's custom standard. Built-in standards live in versioned data files."""

    __tablename__ = "standards"
    __table_args__ = (UniqueConstraint("owner_id", "slug", name="uq_standards_owner_slug"),)

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    family: Mapped[str] = mapped_column(String(16), default="custom", server_default="custom")
    extends: Mapped[str | None] = mapped_column(String(64))  # built-in slug
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StandardVersion(UUIDPk, Base):
    __tablename__ = "standard_versions"
    __table_args__ = (
        UniqueConstraint("standard_id", "version", name="uq_standard_versions_version"),
        CheckConstraint("status IN ('draft','published')", name="status"),
    )

    standard_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("standards.id", ondelete="CASCADE"), index=True, nullable=False
    )
    version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="draft", server_default="draft", nullable=False)
    rules: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
