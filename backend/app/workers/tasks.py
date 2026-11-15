from __future__ import annotations

import asyncio
import uuid

from app.workers.celery_app import celery_app


@celery_app.task(name="system.ping")  # type: ignore[untyped-decorator]
def ping() -> str:
    return "pong"


@celery_app.task(name="jobs.run", acks_late=True)  # type: ignore[untyped-decorator]
def run(job_id: str) -> None:
    """Run any AKSHARA job by id. A fresh engine per task keeps event loops isolated."""
    from app.adapters.storage import LocalBlobStorage
    from app.core.config import get_settings
    from app.db.session import make_engine, make_sessionmaker
    from app.services.jobs.runner import run_job

    async def _main() -> None:
        settings = get_settings()
        engine = make_engine(settings)
        try:
            await run_job(
                settings,
                make_sessionmaker(engine),
                LocalBlobStorage(settings.storage_root),
                uuid.UUID(job_id),
            )
        finally:
            await engine.dispose()

    asyncio.run(_main())
