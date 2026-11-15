from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Response

from app.api.deps import CurrentUser, SessionDep, StateDep, StorageDep
from app.schemas.documents import PageOut
from app.schemas.jobs import JobOut
from app.services.jobs.dispatch import dispatch
from app.services.versions import VersionService

router = APIRouter(tags=["versions"])


@router.get("/versions/{version_id}/adm")
async def get_adm(version_id: uuid.UUID, user: CurrentUser, session: SessionDep, storage: StorageDep) -> dict[str, Any]:
    """The canonical document model (ADM) of this version."""
    adm = await VersionService(session, storage).adm(user.id, version_id)
    return adm.model_dump(mode="json")


@router.get("/versions/{version_id}/outline")
async def get_outline(
    version_id: uuid.UUID, user: CurrentUser, session: SessionDep, storage: StorageDep
) -> list[dict[str, object]]:
    return await VersionService(session, storage).outline(user.id, version_id)


@router.get("/versions/{version_id}/pages", response_model=list[PageOut])
async def list_pages(
    version_id: uuid.UUID, user: CurrentUser, session: SessionDep, storage: StorageDep
) -> list[PageOut]:
    pages = await VersionService(session, storage).pages(user.id, version_id)
    return [PageOut(index=p.page_index, width_pt=p.width_pt, height_pt=p.height_pt, blank=p.blank) for p in pages]


@router.get("/versions/{version_id}/pages/{index}/image")
async def page_image(
    version_id: uuid.UUID, index: int, user: CurrentUser, session: SessionDep, storage: StorageDep
) -> Response:
    data = await VersionService(session, storage).page_image(user.id, version_id, index)
    return Response(
        content=data,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=86400, immutable"},
    )


@router.post("/versions/{version_id}/analyse", response_model=JobOut, status_code=202)
async def reanalyse(
    version_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
    state: StateDep,
) -> JobOut:
    job = await VersionService(session, storage).request_analysis(user.id, version_id)
    await dispatch(state.settings, state.sessionmaker, state.storage, job.id)
    session.expire_all()
    await session.refresh(job)
    return JobOut.model_validate(job)
