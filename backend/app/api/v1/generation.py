from __future__ import annotations

import uuid

from fastapi import APIRouter
from fastapi.responses import Response
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep, StateDep, StorageDep
from app.core.errors import NotFoundError
from app.db.models import Blob, Export, Job
from app.domain.generation.templates import KINDS, new_outline
from app.schemas.documents import UploadOut
from app.schemas.generation import DraftCreate, DraftOut, DraftUpdate, ExportRequest, KindOut
from app.schemas.jobs import JobOut
from app.services.blobs import read_bytes
from app.services.documents.service import DocumentService
from app.services.generation.service import GenerationService
from app.services.jobs.dispatch import dispatch
from app.services.jobs.service import create_job
from app.services.versions import VersionService

router = APIRouter(tags=["generation"])


async def _start(session, state, owner, job_type, subject_type, subject_id, params) -> JobOut:  # type: ignore[no-untyped-def]
    job = await create_job(session, owner, job_type, subject_type=subject_type, subject_id=subject_id, params=params)
    await session.commit()
    job_id = job.id
    await dispatch(state.settings, state.sessionmaker, state.storage, job_id)
    session.expire_all()
    return JobOut.model_validate(await session.get_one(Job, job_id))


@router.get("/generation/kinds", response_model=list[KindOut])
async def kinds() -> list[KindOut]:
    return [KindOut(key=k, label=v["label"], words=v["words"], outline=new_outline(k)) for k, v in KINDS.items()]


@router.post("/generation/drafts", response_model=DraftOut, status_code=201)
async def create_draft(
    body: DraftCreate, user: CurrentUser, session: SessionDep, storage: StorageDep, state: StateDep
) -> DraftOut:
    brief = body.model_dump(include={"topic", "instructions", "tone", "word_target", "author", "citation_style"})
    g = await GenerationService(session, storage, state.settings).create(
        user.id,
        kind=body.kind,
        title=body.title,
        brief=brief,
        references=body.references,
        standard_version_id=body.standard_version_id,
    )
    return DraftOut.model_validate(g)


@router.get("/generation/drafts", response_model=list[DraftOut])
async def list_drafts(user: CurrentUser, session: SessionDep, storage: StorageDep, state: StateDep) -> list[DraftOut]:
    return [
        DraftOut.model_validate(g)
        for g in await GenerationService(session, storage, state.settings).list_drafts(user.id)
    ]


@router.get("/generation/drafts/{draft_id}", response_model=DraftOut)
async def get_draft(
    draft_id: uuid.UUID, user: CurrentUser, session: SessionDep, storage: StorageDep, state: StateDep
) -> DraftOut:
    return DraftOut.model_validate(await GenerationService(session, storage, state.settings).get(user.id, draft_id))


@router.patch("/generation/drafts/{draft_id}", response_model=DraftOut)
async def update_draft(
    draft_id: uuid.UUID, body: DraftUpdate, user: CurrentUser, session: SessionDep, storage: StorageDep, state: StateDep
) -> DraftOut:
    g = await GenerationService(session, storage, state.settings).update(
        user.id, draft_id, body.model_dump(exclude_unset=True)
    )
    return DraftOut.model_validate(g)


@router.post("/generation/drafts/{draft_id}/outline", response_model=JobOut, status_code=202)
async def ai_outline(
    draft_id: uuid.UUID, user: CurrentUser, session: SessionDep, storage: StorageDep, state: StateDep
) -> JobOut:
    await GenerationService(session, storage, state.settings).get(user.id, draft_id)
    return await _start(
        session, state, user.id, "generate_outline", "generation", draft_id, {"session_id": str(draft_id)}
    )


@router.post("/generation/drafts/{draft_id}/sections/{section_id}/generate", response_model=JobOut, status_code=202)
async def ai_section(
    draft_id: uuid.UUID, section_id: str, user: CurrentUser, session: SessionDep, storage: StorageDep, state: StateDep
) -> JobOut:
    await GenerationService(session, storage, state.settings).get(user.id, draft_id)
    return await _start(
        session,
        state,
        user.id,
        "generate_section",
        "generation",
        draft_id,
        {"session_id": str(draft_id), "section_id": section_id},
    )


@router.post("/generation/drafts/{draft_id}/finalize", response_model=UploadOut, status_code=201)
async def finalize(
    draft_id: uuid.UUID, user: CurrentUser, session: SessionDep, storage: StorageDep, state: StateDep
) -> UploadOut:
    from app.api.deps import get_limits
    from app.api.v1.documents import document_out

    owner_id = user.id  # read before any session.expire_all()
    doc, version = await GenerationService(session, storage, state.settings).finalize(owner_id, draft_id)
    doc_id, version_id = doc.id, version.id
    job = await VersionService(session, storage).request_analysis(owner_id, version_id)
    job_id = job.id
    await dispatch(state.settings, state.sessionmaker, state.storage, job_id)
    session.expire_all()
    view = await DocumentService(session, storage, get_limits(state.settings)).get(owner_id, doc_id)
    return UploadOut(**document_out(view).model_dump(), job_id=job_id)


@router.post("/versions/{version_id}/exports", response_model=JobOut, status_code=202)
async def export(
    version_id: uuid.UUID,
    body: ExportRequest,
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
    state: StateDep,
) -> JobOut:
    await VersionService(session, storage).owned(user.id, version_id)
    return await _start(
        session,
        state,
        user.id,
        "export",
        "document_version",
        version_id,
        {"version_id": str(version_id), "format": body.format},
    )


@router.get("/exports/{export_id}/file")
async def export_file(export_id: uuid.UUID, user: CurrentUser, session: SessionDep, storage: StorageDep) -> Response:
    row = (
        await session.execute(
            select(Export, Blob)
            .join(Blob, Blob.sha256 == Export.blob)
            .where(Export.id == export_id, Export.owner_id == user.id)
        )
    ).first()
    if row is None:
        raise NotFoundError("Export not found.", code="EXPORT_NOT_FOUND")
    exp, blob = row
    ascii_name = exp.filename.encode("ascii", "ignore").decode().replace('"', "") or "document"
    return Response(
        read_bytes(storage, blob.sha256),
        media_type=blob.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{ascii_name}"', "Cache-Control": "private, no-store"},
    )
