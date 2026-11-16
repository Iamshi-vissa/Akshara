from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk


class GenerationSession(UUIDPk, Timestamps, Base):
    """An outline-first draft. Text written by the user and by the model is kept apart."""

    __tablename__ = "generation_sessions"
    __table_args__ = (CheckConstraint("status IN ('draft','finalized')", name="status"),)

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # research_paper | presentation | ...
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    brief: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    outline: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    sections: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    references: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    standard_version_id: Mapped[uuid.UUID | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(16), default="draft", server_default="draft", nullable=False)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    notes: Mapped[str | None] = mapped_column(Text)


class Export(UUIDPk, Base):
    __tablename__ = "exports"

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False
    )
    format: Mapped[str] = mapped_column(String(8), nullable=False)
    blob: Mapped[str] = mapped_column(ForeignKey("blobs.sha256", ondelete="RESTRICT"), nullable=False)
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
