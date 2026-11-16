from __future__ import annotations

from fastapi import APIRouter

from app.adapters.formats.pptx_exporter import THEMES
from app.adapters.llm import get_provider
from app.api.deps import CurrentUser, SessionDep, StateDep, StorageDep
from app.core.errors import AppError
from app.db.models import Job
from app.schemas.jobs import JobOut
from app.schemas.presentations import PresentationCreate, ThemeOut
from app.services.jobs.dispatch import dispatch
from app.services.jobs.service import create_job
from app.services.presentations.service import themes
from app.services.versions import VersionService

router = APIRouter(tags=["presentations"])


@router.get("/presentations/themes", response_model=list[ThemeOut])
async def list_themes() -> list[ThemeOut]:
    return [ThemeOut(**t) for t in themes()]


@router.post("/presentations", response_model=JobOut, status_code=202)
async def create_presentation(
    body: PresentationCreate, user: CurrentUser, session: SessionDep, storage: StorageDep, state: StateDep
) -> JobOut:
    owner_id = user.id
    if body.theme not in THEMES:
        raise AppError("Unknown theme.", code="UNKNOWN_THEME", status_code=422)
    # Fail fast on problems the job would only discover later.
    if body.source == "document":
        assert body.version_id is not None
        await VersionService(session, storage).owned(owner_id, body.version_id)
    if body.source == "brief":
        if get_provider(state.settings.llm_provider, state.settings.llm_model) is None:
            raise AppError("AI drafting is not configured on this server.", code="LLM_UNAVAILABLE", status_code=503)
        if not user.allow_external_llm:
            raise AppError(
                "Allow external AI providers in Settings before using AI drafting.",
                code="LLM_CONSENT_REQUIRED",
                status_code=403,
            )
    params = body.model_dump(mode="json")
    job = await create_job(
        session,
        owner_id,
        "presentation",
        subject_type="document_version" if body.version_id else None,
        subject_id=body.version_id,
        params=params,
    )
    await session.commit()
    job_id = job.id
    await dispatch(state.settings, state.sessionmaker, state.storage, job_id)
    session.expire_all()
    return JobOut.model_validate(await session.get_one(Job, job_id))
