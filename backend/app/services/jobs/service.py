"""Background job tracking and dispatch."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.db.models import Job


class JobService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_jobs(self, owner_id: uuid.UUID, *, status: str | None = None, limit: int = 50) -> list[Job]:
        stmt = select(Job).where(Job.owner_id == owner_id)
        if status:
            stmt = stmt.where(Job.status == status)
        return list((await self.session.scalars(stmt.order_by(Job.id.desc()).limit(limit))).all())

    async def get(self, owner_id: uuid.UUID, job_id: uuid.UUID) -> Job:
        job = await self.session.scalar(select(Job).where(Job.id == job_id, Job.owner_id == owner_id))
        if job is None:
            raise NotFoundError("Job not found.", code="JOB_NOT_FOUND")
        return job


async def create_job(
    session: AsyncSession,
    owner_id: uuid.UUID,
    job_type: str,
    *,
    subject_type: str | None = None,
    subject_id: uuid.UUID | None = None,
    params: dict[str, Any] | None = None,
) -> Job:
    job = Job(
        owner_id=owner_id,
        type=job_type,
        status="queued",
        subject_type=subject_type,
        subject_id=subject_id,
        params=params or {},
    )
    session.add(job)
    await session.flush()
    return job
