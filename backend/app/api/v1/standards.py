from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Response, UploadFile, status
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, SessionDep, StateDep, StorageDep
from app.core.errors import AppError, UnsupportedFileError
from app.db.models import Job
from app.domain.udse.schema import Rule
from app.schemas.jobs import JobOut
from app.schemas.standards import (
    CandidateOut,
    ExtractionOut,
    RulesUpdate,
    StandardCreate,
    StandardDetail,
    StandardOut,
    StandardVersionOut,
    ValidationRequest,
)
from app.services.jobs.dispatch import dispatch
from app.services.jobs.service import create_job
from app.services.standards.service import StandardService
from app.services.versions import VersionService

router = APIRouter(tags=["standards"])


def _dump(rules: list[Rule]) -> list[dict[str, Any]]:
    return [r.model_dump(mode="json", exclude_none=True) for r in rules]


@router.get("/standards", response_model=list[StandardOut])
async def list_standards(user: CurrentUser, session: SessionDep) -> list[StandardOut]:
    svc = StandardService(session)
    out = [
        StandardOut(
            id=None,
            slug=b.profile.slug,
            name=b.profile.name,
            family=b.profile.family,
            description=b.profile.description,
            builtin=True,
            notice=b.profile.notice,
            versions=[
                StandardVersionOut(
                    id=b.version_id, version=b.profile.version, status="published", rule_count=len(b.profile.rules)
                )
            ],
        )
        for b in svc.builtins()
    ]
    for st, versions in await svc.custom(user.id):
        out.append(
            StandardOut(
                id=st.id,
                slug=st.slug,
                name=st.name,
                family=st.family,
                description=st.description,
                builtin=False,
                extends=st.extends,
                versions=[
                    StandardVersionOut(
                        id=v.id,
                        version=str(v.version),
                        status=v.status,
                        rule_count=len(v.rules),
                        created_at=v.created_at,
                        published_at=v.published_at,
                    )
                    for v in versions
                ],
            )
        )
    return out


@router.get("/standard-versions/{version_id}", response_model=StandardDetail)
async def get_standard_version(version_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> StandardDetail:
    svc = StandardService(session)
    r = await svc.resolve(user.id, version_id)
    own = None
    if not r.builtin:
        sv, _ = await svc._own_version(user.id, version_id)
        own = sv.rules
    p = r.profile
    return StandardDetail(
        version_id=r.version_id,
        standard_id=r.standard_id,
        slug=p.slug,
        name=p.name,
        family=p.family,
        description=p.description,
        builtin=r.builtin,
        status=r.status,
        version=p.version,
        extends=p.extends,
        notice=p.notice,
        rules=_dump(p.rules),
        own_rules=own,
    )


@router.post("/standards", response_model=StandardDetail, status_code=status.HTTP_201_CREATED)
async def create_standard(body: StandardCreate, user: CurrentUser, session: SessionDep) -> StandardDetail:
    svc = StandardService(session)
    _, sv = await svc.create(user.id, body.name, body.description, body.extends, body.rules)
    return await get_standard_version(sv.id, user, session)


@router.put("/standard-versions/{version_id}/rules", response_model=StandardDetail)
async def update_rules(
    version_id: uuid.UUID, body: RulesUpdate, user: CurrentUser, session: SessionDep
) -> StandardDetail:
    await StandardService(session).update_rules(user.id, version_id, body.rules)
    return await get_standard_version(version_id, user, session)


@router.post("/standard-versions/{version_id}/publish", response_model=StandardDetail)
async def publish(version_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> StandardDetail:
    await StandardService(session).publish(user.id, version_id)
    return await get_standard_version(version_id, user, session)


@router.post("/standards/{standard_id}/versions", response_model=StandardDetail, status_code=201)
async def new_draft(standard_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> StandardDetail:
    sv = await StandardService(session).new_draft(user.id, standard_id)
    return await get_standard_version(sv.id, user, session)


@router.delete("/standards/{standard_id}", status_code=204)
async def delete_standard(standard_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> Response:
    await StandardService(session).delete(user.id, standard_id)
    return Response(status_code=204)


@router.get("/udse/rule-schema")
async def rule_schema() -> dict[str, Any]:
    """JSON Schema for a UDSE rule (used by the rule editor)."""
    return Rule.model_json_schema()


@router.post("/versions/{version_id}/validations", response_model=JobOut, status_code=202)
async def validate(
    version_id: uuid.UUID,
    body: ValidationRequest,
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
    state: StateDep,
) -> JobOut:
    await VersionService(session, storage).owned(user.id, version_id)
    await StandardService(session).resolve(user.id, body.standard_version_id)  # 404 if not visible
    job = await create_job(
        session,
        user.id,
        "validate",
        subject_type="document_version",
        subject_id=version_id,
        params={"version_id": str(version_id), "standard_version_id": str(body.standard_version_id)},
    )
    await session.commit()
    job_id = job.id
    await dispatch(state.settings, state.sessionmaker, state.storage, job_id)
    session.expire_all()
    return JobOut.model_validate(await session.get_one(Job, job_id))


# --- custom standard builder: extract candidate rules from an uploaded guideline ---------------

MAX_GUIDELINE_TEXT = 400_000


def _guideline_text(path: Path, kind: str) -> str:
    if kind == "pdf":
        import pymupdf

        with pymupdf.open(path) as pdf:  # type: ignore[no-untyped-call]
            return "\n".join(page.get_text("text") for page in pdf)
    from app.adapters.formats import import_document

    adm = import_document(path, kind)
    return "\n".join(getattr(b, "text", "") for b in adm.body if getattr(b, "text", ""))


@router.post("/standards/extract", response_model=ExtractionOut)
async def extract_rules(
    user: CurrentUser,
    state: StateDep,
    file: Annotated[UploadFile | None, File(description="A guideline as .docx, .pdf or .txt")] = None,
    text: Annotated[str | None, Form(max_length=MAX_GUIDELINE_TEXT)] = None,
) -> ExtractionOut:
    """Candidate rules, each grounded in a verbatim quote. Nothing is saved: a person reviews them
    and creates a draft standard from the ones they accept (POST /standards)."""
    from app.api.deps import get_limits
    from app.api.v1.documents import _spool
    from app.core.filesafety import FileRejected, inspect_file
    from app.domain.udse.extraction import extract

    name = "Pasted text"
    if file is not None and file.filename:
        limits = get_limits(state.settings)
        temp = await _spool(file, limits.max_bytes)
        try:
            name = file.filename
            if file.filename.lower().endswith(".txt"):
                raw = temp.read_bytes()
                if len(raw) > MAX_GUIDELINE_TEXT * 4:
                    raise AppError("The text file is too large.", code="FILE_TOO_LARGE", status_code=413)
                try:
                    source = raw.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise AppError("Text files must be UTF-8.", code="BAD_ENCODING", status_code=415) from exc
            else:
                try:
                    info = await run_in_threadpool(inspect_file, temp, file.filename, limits)
                except FileRejected as exc:
                    raise UnsupportedFileError(exc.message, code=exc.code, status_code=415) from exc
                if info.kind == "pptx":
                    raise AppError(
                        "Upload guidelines as DOCX, PDF or text.", code="UNSUPPORTED_GUIDELINE", status_code=415
                    )
                source = await run_in_threadpool(_guideline_text, temp, info.kind)
        finally:
            temp.unlink(missing_ok=True)
    elif text and text.strip():
        source = text
    else:
        raise AppError("Upload a guideline file or paste its text.", code="NO_SOURCE", status_code=422)
    source = source[:MAX_GUIDELINE_TEXT]
    candidates = await run_in_threadpool(extract, source)
    return ExtractionOut(
        source_name=name,
        characters=len(source),
        candidates=[
            CandidateOut(rule=c.rule, quote=c.quote, evidence_verified=c.evidence_verified, problems=c.problems)
            for c in candidates
        ],
    )
