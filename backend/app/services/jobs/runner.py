"""Job execution shared by Celery workers and inline mode.

A handler receives a :class:`JobContext` and the job's params, does its work in its own
transactions, and returns a JSON-serialisable result. Failures are recorded on the job with a
user-safe message; the full traceback goes to the logs only.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.storage import BlobStorage
from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import Job

logger = logging.getLogger(__name__)


@dataclass
class JobContext:
    settings: Settings
    sessionmaker: async_sessionmaker[AsyncSession]
    storage: BlobStorage
    job_id: uuid.UUID
    owner_id: uuid.UUID

    async def progress(self, fraction: float) -> None:
        async with self.sessionmaker() as s:
            job = await s.get(Job, self.job_id)
            if job is not None:
                job.progress = max(0.0, min(1.0, fraction))
                await s.commit()


Handler = Callable[[JobContext, dict[str, Any]], Awaitable[dict[str, Any]]]
HANDLERS: dict[str, Handler] = {}


def handler(job_type: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        HANDLERS[job_type] = fn
        return fn

    return register


async def run_job(
    settings: Settings,
    maker: async_sessionmaker[AsyncSession],
    storage: BlobStorage,
    job_id: uuid.UUID,
) -> None:
    from app.services import job_handlers  # noqa: F401  (registers handlers)

    async with maker() as s:
        job = await s.get(Job, job_id)
        if job is None or job.status not in ("queued", "running"):
            return
        job.status, job.started_at = "running", datetime.now(UTC)
        await s.commit()
        job_type, params, owner = job.type, dict(job.params or {}), job.owner_id

    ctx = JobContext(
        settings=settings, sessionmaker=maker, storage=storage, job_id=job_id, owner_id=owner
    )
    fn = HANDLERS.get(job_type)
    try:
        if fn is None:
            raise AppError(f"Unknown job type: {job_type}", code="UNKNOWN_JOB")
        result = await fn(ctx, params)
        status, error_code, error_message = "succeeded", None, None
    except AppError as exc:
        result, status, error_code, error_message = None, "failed", exc.code, exc.message
    except Exception:
        logger.exception("job failed", extra={"fields": {"job_id": str(job_id), "type": job_type}})
        result, status = None, "failed"
        error_code, error_message = (
            "JOB_FAILED",
            "Processing failed. Please try again or contact support.",
        )

    async with maker() as s:
        job = await s.get(Job, job_id)
        if job is not None:
            job.status, job.result = status, result
            job.error_code, job.error_message = error_code, error_message
            job.progress = 1.0 if status == "succeeded" else job.progress
            job.finished_at = datetime.now(UTC)
            await s.commit()
