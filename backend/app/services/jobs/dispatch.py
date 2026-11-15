"""Send a committed job to its executor (Celery worker, or inline for tests/dev)."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.storage import BlobStorage
from app.core.config import Settings
from app.services.jobs.runner import run_job


async def dispatch(
    settings: Settings,
    maker: async_sessionmaker[AsyncSession],
    storage: BlobStorage,
    job_id: uuid.UUID,
) -> None:
    if settings.job_mode == "inline":
        await run_job(settings, maker, storage, job_id)
        return
    from app.workers.celery_app import celery_app

    celery_app.send_task("jobs.run", args=[str(job_id)])
