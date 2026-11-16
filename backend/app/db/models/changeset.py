from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPk


class ChangeSet(UUIDPk, Base):
    __tablename__ = "changesets"
    __table_args__ = (
        CheckConstraint("status IN ('open','applying','applied','discarded','stale','failed')", name="status"),
        CheckConstraint("source IN ('autocorrect','grammar','ai_edit','manual')", name="source"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    base_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="open", server_default="open", nullable=False)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    result_version_id: Mapped[uuid.UUID | None] = mapped_column()
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ChangeProposal(UUIDPk, Base):
    __tablename__ = "change_proposals"
    __table_args__ = (
        CheckConstraint("decision IN ('pending','accepted','rejected')", name="decision"),
        CheckConstraint("risk IN ('formatting_only','structural','content_change')", name="risk"),
    )

    changeset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("changesets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    ops: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    risk: Mapped[str] = mapped_column(String(16), nullable=False)
    before: Mapped[str] = mapped_column(Text, default="")
    after: Mapped[str] = mapped_column(Text, default="")
    node_ids: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, server_default="{}")
    finding_ids: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, server_default="{}")
    rule_id: Mapped[str | None] = mapped_column(String(128))
    origin: Mapped[str] = mapped_column(
        String(16), default="deterministic", server_default="deterministic"
    )  # deterministic|grammar|llm|user
    decision: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending", nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
