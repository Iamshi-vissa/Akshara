"""Run inspections on a version and read them back (owner-scoped)."""

from __future__ import annotations

import uuid
from typing import Any

from anyio.to_thread import run_sync
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.storage import BlobStorage
from app.core.errors import AppError, NotFoundError
from app.db.models import Document, DocumentVersion, FindingRow, InspectionRun
from app.domain.adm.model import AdmDocument
from app.domain.inspection import Finding, InspectContext, inspect
from app.domain.scoring import Scored, score
from app.services import audit
from app.services.blobs import read_json
from app.services.jobs.runner import JobContext, handler


def finding_rows(run_id: uuid.UUID, findings: list[Finding]) -> list[FindingRow]:
    return [
        FindingRow(
            run_id=run_id,
            ordinal=i,
            code=f.code,
            category=f.category,
            severity=f.severity,
            rule_id=f.rule_id,
            constraint_kind=f.constraint,
            node_ids=f.node_ids,
            page_index=f.page,
            bbox=list(f.bbox) if f.bbox else None,
            location=f.location,
            message=f.message,
            explanation=f.explanation,
            recommendation=f.recommendation,
            expected=f.expected,
            actual=f.actual,
            detector=f.detector,
            confidence=round(f.confidence, 3),
            fix_available=f.fix_available,
        )
        for i, f in enumerate(findings)
    ]


async def load_inputs(
    s: AsyncSession, storage: BlobStorage, owner_id: uuid.UUID, version_id: uuid.UUID
) -> tuple[DocumentVersion, Document, AdmDocument, dict[str, Any] | None]:
    row = (
        await s.execute(
            select(DocumentVersion, Document)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(DocumentVersion.id == version_id, Document.owner_id == owner_id)
        )
    ).first()
    if row is None:
        raise NotFoundError("Version not found.", code="VERSION_NOT_FOUND")
    version, doc = row
    if version.adm_blob is None:
        raise AppError("Analyse the document before inspecting it.", code="NOT_ANALYSED", status_code=409)
    adm = AdmDocument.model_validate(read_json(storage, version.adm_blob))
    layout = read_json(storage, version.layout_blob) if version.layout_blob else None
    return version, doc, adm, layout


async def run_inspection(ctx: JobContext, version_id: uuid.UUID) -> uuid.UUID:
    async with ctx.sessionmaker() as s:
        _, _, adm, layout = await load_inputs(s, ctx.storage, ctx.owner_id, version_id)
    result = await run_sync(inspect, InspectContext(adm=adm, layout=layout))
    scores = score(Scored(f.category, f.severity, f.confidence) for f in result.findings)
    async with ctx.sessionmaker() as s:
        run = InspectionRun(
            owner_id=ctx.owner_id,
            version_id=version_id,
            kind="inspection",
            engine_version=result.engine_version,
            stats={
                "scores": scores,
                "checks_run": result.checks_run,
                "not_evaluated": result.not_evaluated,
                "total": len(result.findings),
            },
        )
        s.add(run)
        await s.flush()
        s.add_all(finding_rows(run.id, result.findings))
        audit.record(
            s,
            "document.inspected",
            owner_id=ctx.owner_id,
            subject_type="document_version",
            subject_id=version_id,
            findings=len(result.findings),
        )
        await s.commit()
        return run.id


@handler("inspect")
async def inspect_job(ctx: JobContext, params: dict[str, Any]) -> dict[str, Any]:
    run_id = await run_inspection(ctx, uuid.UUID(params["version_id"]))
    return {"run_id": str(run_id)}


class InspectionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def run(self, owner_id: uuid.UUID, run_id: uuid.UUID) -> InspectionRun:
        r = await self.session.scalar(
            select(InspectionRun).where(InspectionRun.id == run_id, InspectionRun.owner_id == owner_id)
        )
        if r is None:
            raise NotFoundError("Inspection not found.", code="INSPECTION_NOT_FOUND")
        return r

    async def latest(
        self, owner_id: uuid.UUID, version_id: uuid.UUID, kind: str = "inspection"
    ) -> InspectionRun | None:
        return await self.session.scalar(
            select(InspectionRun)
            .where(
                InspectionRun.version_id == version_id,
                InspectionRun.owner_id == owner_id,
                InspectionRun.kind == kind,
            )
            .order_by(InspectionRun.created_at.desc(), InspectionRun.id.desc())
            .limit(1)
        )

    async def findings(
        self,
        owner_id: uuid.UUID,
        run_id: uuid.UUID,
        *,
        severity: str | None = None,
        category: str | None = None,
        status: str | None = None,
    ) -> list[FindingRow]:
        await self.run(owner_id, run_id)
        stmt = select(FindingRow).where(FindingRow.run_id == run_id)
        if severity:
            stmt = stmt.where(FindingRow.severity == severity)
        if category:
            stmt = stmt.where(FindingRow.category == category)
        if status:
            stmt = stmt.where(FindingRow.status == status)
        return list((await self.session.scalars(stmt.order_by(FindingRow.ordinal))).all())

    async def set_status(
        self, owner_id: uuid.UUID, finding_id: uuid.UUID, status: str, reason: str | None
    ) -> FindingRow:
        row = (
            await self.session.execute(
                select(FindingRow)
                .join(InspectionRun, InspectionRun.id == FindingRow.run_id)
                .where(FindingRow.id == finding_id, InspectionRun.owner_id == owner_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Finding not found.", code="FINDING_NOT_FOUND")
        row.status = status
        row.dismiss_reason = reason if status == "dismissed" else None
        await self.session.commit()
        return row
