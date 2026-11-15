from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPk


class InspectionRun(UUIDPk, Base):
    __tablename__ = "inspection_runs"
    __table_args__ = (Index("ix_inspection_runs_version", "version_id", "created_at"),)

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # inspection | udse | visual
    standard_version_id: Mapped[uuid.UUID | None] = mapped_column()
    engine_version: Mapped[str] = mapped_column(String(32), nullable=False)
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class FindingRow(UUIDPk, Base):
    __tablename__ = "findings"
    __table_args__ = (
        CheckConstraint("severity IN ('critical','high','medium','low','info')", name="severity"),
        CheckConstraint("status IN ('open','dismissed','fixed')", name="status"),
        Index("ix_findings_run_severity", "run_id", "severity"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inspection_runs.id", ondelete="CASCADE"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="open", server_default="open")
    dismiss_reason: Mapped[str | None] = mapped_column(Text)
    rule_id: Mapped[str | None] = mapped_column(String(128))
    constraint_kind: Mapped[str | None] = mapped_column(String(8))
    node_ids: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, server_default="{}")
    page_index: Mapped[int | None] = mapped_column(Integer)
    bbox: Mapped[list[float] | None] = mapped_column(ARRAY(Float))
    location: Mapped[str] = mapped_column(Text, default="")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    expected: Mapped[Any] = mapped_column(JSONB)
    actual: Mapped[Any] = mapped_column(JSONB)
    detector: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    fix_available: Mapped[bool] = mapped_column(default=False)
