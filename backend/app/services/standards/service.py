"""Standards: built-in profiles (files) + user custom standards (database), and validation."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from anyio.to_thread import run_sync
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ConflictError, NotFoundError
from app.db.models import Document, DocumentVersion, InspectionRun, Standard, StandardVersion
from app.domain.udse.engine import evaluate
from app.domain.udse.schema import Rule, StandardProfile, merge
from app.services import audit
from app.services.inspections.service import finding_rows, load_inputs
from app.services.jobs.runner import JobContext, handler
from app.standards import builtin_profiles, builtin_version_id


@dataclass
class ResolvedStandard:
    version_id: uuid.UUID
    profile: StandardProfile
    builtin: bool
    standard_id: uuid.UUID | None
    status: str  # published | draft


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return (s or "standard")[:56]


def validate_rules(raw: list[dict[str, Any]]) -> list[Rule]:
    try:
        rules = [Rule.model_validate(r) for r in raw]
    except ValidationError as exc:
        errors = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()][:20]
        raise AppError(
            "One or more rules are invalid.", code="INVALID_RULES", status_code=422, details={"errors": errors}
        ) from exc
    ids = [r.id for r in rules]
    if len(ids) != len(set(ids)):
        raise AppError("Rule ids must be unique.", code="INVALID_RULES", status_code=422)
    return rules


class StandardService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- read ---------------------------------------------------------------------------
    def builtins(self) -> list[ResolvedStandard]:
        return [
            ResolvedStandard(builtin_version_id(p.slug, p.version), p, True, None, "published")
            for p in builtin_profiles().values()
        ]

    async def custom(self, owner_id: uuid.UUID) -> list[tuple[Standard, list[StandardVersion]]]:
        stds = (
            await self.session.scalars(
                select(Standard)
                .where(Standard.owner_id == owner_id, Standard.deleted_at.is_(None))
                .order_by(Standard.created_at)
            )
        ).all()
        out = []
        for st in stds:
            versions = (
                await self.session.scalars(
                    select(StandardVersion)
                    .where(StandardVersion.standard_id == st.id)
                    .order_by(StandardVersion.version)
                )
            ).all()
            out.append((st, list(versions)))
        return out

    async def resolve(self, owner_id: uuid.UUID, version_id: uuid.UUID) -> ResolvedStandard:
        for b in self.builtins():
            if b.version_id == version_id:
                return b
        row = (
            await self.session.execute(
                select(StandardVersion, Standard)
                .join(Standard, Standard.id == StandardVersion.standard_id)
                .where(StandardVersion.id == version_id, Standard.owner_id == owner_id, Standard.deleted_at.is_(None))
            )
        ).first()
        if row is None:
            raise NotFoundError("Standard not found.", code="STANDARD_NOT_FOUND")
        sv, st = row
        own = StandardProfile(
            slug=st.slug,
            name=st.name,
            version=f"{sv.version}",
            family="custom",
            description=st.description,
            extends=st.extends,
            rules=[Rule.model_validate(r) for r in sv.rules],
        )
        profile = merge(builtin_profiles()[st.extends], own) if st.extends in builtin_profiles() else own
        return ResolvedStandard(sv.id, profile, False, st.id, sv.status)

    # --- write --------------------------------------------------------------------------
    async def create(
        self, owner_id: uuid.UUID, name: str, description: str, extends: str | None, rules: list[dict[str, Any]]
    ) -> tuple[Standard, StandardVersion]:
        if extends and extends not in builtin_profiles():
            raise AppError("Unknown built-in standard to extend.", code="UNKNOWN_BASE", status_code=422)
        validated = validate_rules(rules)
        st = Standard(
            owner_id=owner_id, slug=_slugify(name), name=name.strip(), description=description.strip(), extends=extends
        )
        self.session.add(st)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError("You already have a standard with this name.", code="STANDARD_EXISTS") from exc
        sv = StandardVersion(
            standard_id=st.id,
            version=1,
            status="draft",
            rules=[r.model_dump(mode="json", exclude_none=True) for r in validated],
        )
        self.session.add(sv)
        audit.record(self.session, "standard.created", owner_id=owner_id, subject_type="standard", subject_id=st.id)
        await self.session.commit()
        return st, sv

    async def _own_version(self, owner_id: uuid.UUID, version_id: uuid.UUID) -> tuple[StandardVersion, Standard]:
        row = (
            await self.session.execute(
                select(StandardVersion, Standard)
                .join(Standard, Standard.id == StandardVersion.standard_id)
                .where(StandardVersion.id == version_id, Standard.owner_id == owner_id, Standard.deleted_at.is_(None))
            )
        ).first()
        if row is None:
            raise NotFoundError("Standard version not found.", code="STANDARD_NOT_FOUND")
        return row[0], row[1]

    async def update_rules(
        self, owner_id: uuid.UUID, version_id: uuid.UUID, rules: list[dict[str, Any]]
    ) -> StandardVersion:
        sv, _ = await self._own_version(owner_id, version_id)
        if sv.status != "draft":
            raise ConflictError(
                "Published versions are immutable. Create a new draft to edit.", code="VERSION_PUBLISHED"
            )
        sv.rules = [r.model_dump(mode="json", exclude_none=True) for r in validate_rules(rules)]
        await self.session.commit()
        return sv

    async def publish(self, owner_id: uuid.UUID, version_id: uuid.UUID) -> StandardVersion:
        sv, st = await self._own_version(owner_id, version_id)
        if sv.status == "published":
            return sv
        if not sv.rules and not st.extends:
            raise AppError("A standard needs at least one rule.", code="EMPTY_STANDARD", status_code=422)
        sv.status, sv.published_at = "published", datetime.now(UTC)
        audit.record(
            self.session,
            "standard.published",
            owner_id=owner_id,
            subject_type="standard",
            subject_id=st.id,
            version=sv.version,
        )
        await self.session.commit()
        return sv

    async def new_draft(self, owner_id: uuid.UUID, standard_id: uuid.UUID) -> StandardVersion:
        st = await self.session.scalar(
            select(Standard).where(
                Standard.id == standard_id, Standard.owner_id == owner_id, Standard.deleted_at.is_(None)
            )
        )
        if st is None:
            raise NotFoundError("Standard not found.", code="STANDARD_NOT_FOUND")
        latest = await self.session.scalar(
            select(StandardVersion)
            .where(StandardVersion.standard_id == st.id)
            .order_by(StandardVersion.version.desc())
            .limit(1)
        )
        if latest is not None and latest.status == "draft":
            return latest
        sv = StandardVersion(
            standard_id=st.id,
            version=(latest.version + 1) if latest else 1,
            status="draft",
            rules=list(latest.rules) if latest else [],
        )
        self.session.add(sv)
        await self.session.commit()
        return sv

    async def delete(self, owner_id: uuid.UUID, standard_id: uuid.UUID) -> None:
        st = await self.session.scalar(
            select(Standard).where(
                Standard.id == standard_id, Standard.owner_id == owner_id, Standard.deleted_at.is_(None)
            )
        )
        if st is None:
            raise NotFoundError("Standard not found.", code="STANDARD_NOT_FOUND")
        st.deleted_at = datetime.now(UTC)
        await self.session.commit()


def rule_results_summary(results: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": r.rule.id,
            "title": r.rule.title,
            "kind": r.rule.kind,
            "severity": r.rule.severity,
            "category": r.rule.category,
            "status": r.status,
            "reason": r.reason,
            "checked": r.checked,
            "violations": len(r.violations),
            "verification": r.rule.provenance.verification if r.rule.provenance else None,
            "source": r.rule.provenance.source if r.rule.provenance else None,
        }
        for r in results
    ]


async def run_validation(ctx: JobContext, version_id: uuid.UUID, standard_version_id: uuid.UUID) -> uuid.UUID:
    async with ctx.sessionmaker() as s:
        _, doc, adm, _ = await load_inputs(s, ctx.storage, ctx.owner_id, version_id)
        resolved = await StandardService(s).resolve(ctx.owner_id, standard_version_id)
        doc_id = doc.id
    result = await run_sync(evaluate, resolved.profile, adm)
    async with ctx.sessionmaker() as s:
        run = InspectionRun(
            owner_id=ctx.owner_id,
            version_id=version_id,
            kind="udse",
            standard_version_id=standard_version_id,
            engine_version=result.engine_version,
            stats={
                "compliance": result.compliance,
                "rules": rule_results_summary(result.results),
                "not_evaluated": [
                    {"rule": r.rule.id, "reason": r.reason} for r in result.results if r.status == "not_evaluated"
                ],
                "standard": {
                    "name": resolved.profile.name,
                    "version": resolved.profile.version,
                    "builtin": resolved.builtin,
                    "status": resolved.status,
                    "notice": resolved.profile.notice,
                },
                "total": len(result.findings),
            },
        )
        s.add(run)
        await s.flush()
        s.add_all(finding_rows(run.id, result.findings))
        d = await s.get(Document, doc_id)
        if d is not None:
            d.applied_standard_version_id = standard_version_id
        audit.record(
            s,
            "document.validated",
            owner_id=ctx.owner_id,
            subject_type="document_version",
            subject_id=version_id,
            standard=resolved.profile.slug,
            score=result.compliance["score"],
        )
        await s.commit()
        return run.id


@handler("validate")
async def validate_job(ctx: JobContext, params: dict[str, Any]) -> dict[str, Any]:
    run_id = await run_validation(ctx, uuid.UUID(params["version_id"]), uuid.UUID(params["standard_version_id"]))
    return {"run_id": str(run_id)}


async def latest_version_of(session: AsyncSession, document_id: uuid.UUID) -> DocumentVersion | None:
    return await session.scalar(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == document_id)
        .order_by(DocumentVersion.number.desc())
        .limit(1)
    )
