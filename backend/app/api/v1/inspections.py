from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Response
from sqlalchemy import select

from app.adapters.render.html_pdf import html_to_pdf
from app.api.deps import CurrentUser, SessionDep, StateDep, StorageDep
from app.core.errors import NotFoundError
from app.db.models import Document, DocumentVersion, InspectionRun
from app.schemas.inspections import (
    FindingOut,
    FindingUpdate,
    InspectionRunOut,
    InspectionWithFindings,
    QualityRow,
)
from app.schemas.jobs import JobOut
from app.services.inspections.service import InspectionService
from app.services.jobs.dispatch import dispatch
from app.services.jobs.service import create_job
from app.services.reports.render import report_html
from app.services.versions import VersionService

router = APIRouter(tags=["inspections"])


@router.post("/versions/{version_id}/inspections", response_model=JobOut, status_code=202)
async def start_inspection(
    version_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
    state: StateDep,
) -> JobOut:
    await VersionService(session, storage).owned(user.id, version_id)
    job = await create_job(
        session,
        user.id,
        "inspect",
        subject_type="document_version",
        subject_id=version_id,
        params={"version_id": str(version_id)},
    )
    await session.commit()
    job_id = job.id
    await dispatch(state.settings, state.sessionmaker, state.storage, job_id)
    session.expire_all()
    return JobOut.model_validate(await session.get_one(type(job), job_id))


@router.get("/versions/{version_id}/inspections/latest", response_model=InspectionWithFindings | None)
async def latest_inspection(
    version_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
    kind: Literal["inspection", "udse", "visual", "references"] = "inspection",
) -> InspectionWithFindings | None:
    await VersionService(session, storage).owned(user.id, version_id)
    svc = InspectionService(session)
    run = await svc.latest(user.id, version_id, kind)
    if run is None:
        return None
    findings = await svc.findings(user.id, run.id)
    return InspectionWithFindings(
        **InspectionRunOut.model_validate(run).model_dump(),
        findings=[FindingOut.model_validate(f) for f in findings],
    )


@router.get("/inspections/{run_id}", response_model=InspectionRunOut)
async def get_run(run_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> InspectionRunOut:
    return InspectionRunOut.model_validate(await InspectionService(session).run(user.id, run_id))


@router.get("/inspections/{run_id}/findings", response_model=list[FindingOut])
async def list_findings(
    run_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    severity: str | None = None,
    category: str | None = None,
    status: str | None = None,
) -> list[FindingOut]:
    rows = await InspectionService(session).findings(
        user.id, run_id, severity=severity, category=category, status=status
    )
    return [FindingOut.model_validate(r) for r in rows]


@router.patch("/findings/{finding_id}", response_model=FindingOut)
async def update_finding(
    finding_id: uuid.UUID, body: FindingUpdate, user: CurrentUser, session: SessionDep
) -> FindingOut:
    row = await InspectionService(session).set_status(user.id, finding_id, body.status, body.reason)
    return FindingOut.model_validate(row)


@router.get("/inspections/{run_id}/report")
async def report(
    run_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    format: Literal["json", "html", "pdf"] = "html",
) -> Response:
    svc = InspectionService(session)
    run = await svc.run(user.id, run_id)
    findings = [FindingOut.model_validate(f).model_dump(mode="json") for f in await svc.findings(user.id, run_id)]
    row = (
        await session.execute(
            select(DocumentVersion, Document)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(DocumentVersion.id == run.version_id)
        )
    ).first()
    if row is None:
        raise NotFoundError("Document not found.")
    version, doc = row
    run_json = InspectionRunOut.model_validate(run).model_dump(mode="json")
    if format == "json":
        import json

        return Response(
            json.dumps(
                {
                    "document": doc.title,
                    "version": version.number,
                    "run": run_json,
                    "findings": findings,
                }
            ),
            media_type="application/json",
        )
    title = "AKSHARA compliance report" if run.kind == "udse" else "AKSHARA quality report"
    html = report_html(
        title=title,
        document=doc.title,
        kind=doc.kind,
        version=version.number,
        run=run_json,
        findings=findings,
        compliance=run.stats.get("compliance"),
    )
    if format == "html":
        return Response(
            html,
            media_type="text/html; charset=utf-8",
            headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"},
        )
    pdf = html_to_pdf(html)
    safe = "".join(ch for ch in doc.title if ch.isalnum() or ch in " -_")[:60].strip() or "report"
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe} - report.pdf"'},
    )


@router.get("/quality", response_model=list[QualityRow])
async def quality_overview(user: CurrentUser, session: SessionDep) -> list[QualityRow]:
    """Latest inspection scores for the current version of every document."""
    rows = (
        await session.execute(
            select(Document, InspectionRun)
            .join(InspectionRun, InspectionRun.version_id == Document.current_version_id)
            .where(
                Document.owner_id == user.id,
                Document.deleted_at.is_(None),
                InspectionRun.kind == "inspection",
            )
            .order_by(InspectionRun.created_at.desc())
        )
    ).all()
    seen: set[uuid.UUID] = set()
    out = []
    for doc, run in rows:
        if doc.id in seen:
            continue
        seen.add(doc.id)
        out.append(
            QualityRow(
                document_id=doc.id,
                title=doc.title,
                kind=doc.kind,
                version_id=run.version_id,
                run_id=run.id,
                scores=run.stats.get("scores", {}),
                total=run.stats.get("total", 0),
                created_at=run.created_at,
            )
        )
    return out
