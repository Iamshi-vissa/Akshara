from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter

from app.api.deps import CurrentUser, SessionDep, StateDep, StorageDep
from app.core.errors import AppError
from app.db.models import Job
from app.schemas.common import ApiModel
from app.schemas.jobs import JobOut
from app.services.jobs.dispatch import dispatch
from app.services.jobs.service import create_job
from app.services.versions import VersionService

router = APIRouter(tags=["references"])


class VerifyRequest(ApiModel):
    style: Literal["apa", "ieee", "mla"] | None = None


@router.post("/versions/{version_id}/references/verify", response_model=JobOut, status_code=202)
async def verify_references(
    version_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
    state: StateDep,
    body: VerifyRequest | None = None,
) -> JobOut:
    owner_id = user.id
    if not state.settings.reference_lookups:
        raise AppError("Reference lookups are turned off on this server.", code="LOOKUPS_DISABLED", status_code=503)
    version, _ = await VersionService(session, storage).owned(owner_id, version_id)
    if version.adm_blob is None:
        raise AppError("Analyse the document before checking its references.", code="NOT_ANALYSED", status_code=409)
    job = await create_job(
        session,
        owner_id,
        "verify_references",
        subject_type="document_version",
        subject_id=version_id,
        params={"version_id": str(version_id), "style": body.style if body else None},
    )
    await session.commit()
    job_id = job.id
    await dispatch(state.settings, state.sessionmaker, state.storage, job_id)
    session.expire_all()
    return JobOut.model_validate(await session.get_one(Job, job_id))
