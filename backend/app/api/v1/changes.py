from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Response

from app.api.deps import CurrentUser, SessionDep, StateDep, StorageDep
from app.core.errors import AppError, ConflictError
from app.db.models import ChangeProposal, ChangeSet, Document, Job
from app.domain.adm.diff import diff
from app.schemas.changes import ChangeSetCreate, ChangeSetOut, Decisions, ProposalOut, RevertRequest
from app.schemas.jobs import JobOut
from app.services.changes.service import ChangeService
from app.services.jobs.dispatch import dispatch
from app.services.jobs.service import create_job
from app.services.versions import VersionService

router = APIRouter(tags=["changes"])


def _out(cs: ChangeSet, props: list[ChangeProposal]) -> ChangeSetOut:
    return ChangeSetOut(
        **{k: getattr(cs, k) for k in ChangeSetOut.model_fields if k != "proposals"},
        proposals=[ProposalOut.model_validate(p) for p in props],
    )


@router.post("/documents/{document_id}/changesets", response_model=ChangeSetOut, status_code=201)
async def create_changeset(
    document_id: uuid.UUID,
    body: ChangeSetCreate,
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
    state: StateDep,
) -> ChangeSetOut:
    svc = ChangeService(session, storage, state.settings)
    if body.source == "autocorrect":
        cs = await svc.autocorrect(user.id, document_id)
    elif body.source == "manual":
        cs = await svc.manual(user.id, document_id, [e.model_dump() for e in body.edits])
    elif body.source == "grammar":
        cs = await svc.grammar(user.id, document_id, body.node_ids or None)
    else:
        cs = await svc.ai_edit(user.id, document_id, body.operation or "", body.node_ids, body.tone)
    return _out(*await svc.get(user.id, cs.id))


@router.get("/documents/{document_id}/changesets", response_model=list[ChangeSetOut])
async def list_changesets(
    document_id: uuid.UUID, user: CurrentUser, session: SessionDep, storage: StorageDep, state: StateDep
) -> list[ChangeSetOut]:
    rows = await ChangeService(session, storage, state.settings).list_for(user.id, document_id)
    return [_out(cs, []) for cs in rows]


@router.get("/changesets/{changeset_id}", response_model=ChangeSetOut)
async def get_changeset(
    changeset_id: uuid.UUID, user: CurrentUser, session: SessionDep, storage: StorageDep, state: StateDep
) -> ChangeSetOut:
    return _out(*await ChangeService(session, storage, state.settings).get(user.id, changeset_id))


@router.post("/changesets/{changeset_id}/decisions", response_model=ChangeSetOut)
async def decide(
    changeset_id: uuid.UUID,
    body: Decisions,
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
    state: StateDep,
) -> ChangeSetOut:
    svc = ChangeService(session, storage, state.settings)
    await svc.decide(user.id, changeset_id, dict(body.decisions))
    return _out(*await svc.get(user.id, changeset_id))


@router.post("/changesets/{changeset_id}/apply", response_model=JobOut, status_code=202)
async def apply(
    changeset_id: uuid.UUID, user: CurrentUser, session: SessionDep, storage: StorageDep, state: StateDep
) -> JobOut:
    cs, props = await ChangeService(session, storage, state.settings).get(user.id, changeset_id)
    if cs.status != "open":
        raise ConflictError(f"This change set is {cs.status}.", code="CHANGESET_CLOSED")
    doc = await session.get(Document, cs.document_id)
    if doc is None or doc.current_version_id != cs.base_version_id:
        cs.status = "stale"
        await session.commit()
        raise ConflictError(
            "The document changed after these proposals were made. Create new proposals.", code="CHANGESET_STALE"
        )
    if not any(p.decision == "accepted" for p in props):
        raise AppError("Accept at least one proposal before applying.", code="NOTHING_ACCEPTED", status_code=422)
    job = await create_job(
        session,
        user.id,
        "apply_changeset",
        subject_type="changeset",
        subject_id=cs.id,
        params={"changeset_id": str(cs.id)},
    )
    await session.commit()
    job_id = job.id
    await dispatch(state.settings, state.sessionmaker, state.storage, job_id)
    session.expire_all()
    return JobOut.model_validate(await session.get_one(Job, job_id))


@router.post("/changesets/{changeset_id}/discard", status_code=204)
async def discard(
    changeset_id: uuid.UUID, user: CurrentUser, session: SessionDep, storage: StorageDep, state: StateDep
) -> Response:
    await ChangeService(session, storage, state.settings).discard(user.id, changeset_id)
    return Response(status_code=204)


@router.post("/documents/{document_id}/revert", response_model=JobOut, status_code=202)
async def revert(
    document_id: uuid.UUID,
    body: RevertRequest,
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
    state: StateDep,
) -> JobOut:
    version, doc = await VersionService(session, storage).owned(user.id, body.version_id)
    if doc.id != document_id:
        raise AppError("That version belongs to another document.", code="VERSION_MISMATCH", status_code=422)
    job = await create_job(
        session,
        user.id,
        "revert",
        subject_type="document",
        subject_id=document_id,
        params={"version_id": str(version.id)},
    )
    await session.commit()
    job_id = job.id
    await dispatch(state.settings, state.sessionmaker, state.storage, job_id)
    session.expire_all()
    return JobOut.model_validate(await session.get_one(Job, job_id))


@router.get("/documents/{document_id}/diff")
async def version_diff(
    document_id: uuid.UUID,
    from_version: uuid.UUID,
    to_version: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
) -> dict[str, Any]:
    svc = VersionService(session, storage)
    for vid in (from_version, to_version):
        _, doc = await svc.owned(user.id, vid)
        if doc.id != document_id:
            raise AppError("Versions must belong to this document.", code="VERSION_MISMATCH", status_code=422)
    return diff(await svc.adm(user.id, from_version), await svc.adm(user.id, to_version))
