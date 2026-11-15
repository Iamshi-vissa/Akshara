"""Read access to a version's derived data (ADM, outline, rendered pages), owner-scoped."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.storage import BlobStorage
from app.core.errors import AppError, NotFoundError
from app.db.models import Document, DocumentVersion, Job, RenderPage
from app.domain.adm.model import AdmDocument
from app.domain.adm.outline import outline
from app.services import audit
from app.services.blobs import read_bytes, read_json
from app.services.jobs.service import create_job


class VersionService:
    def __init__(self, session: AsyncSession, storage: BlobStorage) -> None:
        self.session = session
        self.storage = storage

    async def owned(
        self, owner_id: uuid.UUID, version_id: uuid.UUID
    ) -> tuple[DocumentVersion, Document]:
        row = (
            await self.session.execute(
                select(DocumentVersion, Document)
                .join(Document, Document.id == DocumentVersion.document_id)
                .where(
                    DocumentVersion.id == version_id,
                    Document.owner_id == owner_id,
                    Document.deleted_at.is_(None),
                )
            )
        ).first()
        if row is None:
            raise NotFoundError("Version not found.", code="VERSION_NOT_FOUND")
        return row[0], row[1]

    async def adm(self, owner_id: uuid.UUID, version_id: uuid.UUID) -> AdmDocument:
        version, _ = await self.owned(owner_id, version_id)
        if version.adm_blob is None:
            raise AppError(
                "This version has not been analysed yet.",
                code="NOT_ANALYSED",
                status_code=409,
                details={"analysis_status": version.analysis_status},
            )
        return AdmDocument.model_validate(read_json(self.storage, version.adm_blob))

    async def layout(self, owner_id: uuid.UUID, version_id: uuid.UUID) -> dict[str, Any] | None:
        version, _ = await self.owned(owner_id, version_id)
        return read_json(self.storage, version.layout_blob) if version.layout_blob else None

    async def outline(self, owner_id: uuid.UUID, version_id: uuid.UUID) -> list[dict[str, object]]:
        return [n.as_dict() for n in outline(await self.adm(owner_id, version_id))]

    async def pages(self, owner_id: uuid.UUID, version_id: uuid.UUID) -> list[RenderPage]:
        await self.owned(owner_id, version_id)
        rows = await self.session.scalars(
            select(RenderPage)
            .where(RenderPage.version_id == version_id)
            .order_by(RenderPage.page_index)
        )
        return list(rows.all())

    async def page_image(self, owner_id: uuid.UUID, version_id: uuid.UUID, index: int) -> bytes:
        await self.owned(owner_id, version_id)
        page = await self.session.scalar(
            select(RenderPage).where(
                RenderPage.version_id == version_id, RenderPage.page_index == index
            )
        )
        if page is None:
            raise NotFoundError("Page not found.", code="PAGE_NOT_FOUND")
        return read_bytes(self.storage, page.image_blob)

    async def request_analysis(self, owner_id: uuid.UUID, version_id: uuid.UUID) -> Job:
        version, _ = await self.owned(owner_id, version_id)
        version.analysis_status = "pending"
        job = await create_job(
            self.session,
            owner_id,
            "analyse",
            subject_type="document_version",
            subject_id=version_id,
            params={"version_id": str(version_id)},
        )
        audit.record(
            self.session,
            "document.analysis_requested",
            owner_id=owner_id,
            subject_type="document_version",
            subject_id=version_id,
        )
        await self.session.commit()
        return job
