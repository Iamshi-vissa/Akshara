"""Export a version as DOCX/PDF/PPTX. Conversions use the same sandboxed renderer as previews."""

from __future__ import annotations

import uuid
from pathlib import PurePosixPath
from typing import Any

from anyio.to_thread import run_sync
from sqlalchemy import select

from app.adapters.render.renderer import convert_to_pdf
from app.core.errors import AppError, NotFoundError
from app.core.filesafety import MIME_TYPES
from app.db.models import Document, DocumentVersion, Export
from app.services import audit
from app.services.blobs import read_bytes, store_bytes, write_temp
from app.services.jobs.runner import JobContext, handler


@handler("export")
async def export_job(ctx: JobContext, params: dict[str, Any]) -> dict[str, Any]:
    fmt = params["format"]
    async with ctx.sessionmaker() as s:
        row = (
            await s.execute(
                select(DocumentVersion, Document)
                .join(Document, Document.id == DocumentVersion.document_id)
                .where(DocumentVersion.id == uuid.UUID(params["version_id"]), Document.owner_id == ctx.owner_id)
            )
        ).first()
        if row is None:
            raise NotFoundError("Version not found.", code="VERSION_NOT_FOUND")
        version, doc = row
        kind, sha, stem, number = (
            doc.kind,
            version.source_blob,
            PurePosixPath(doc.original_filename).stem,
            version.number,
        )
    if fmt == kind:
        data = read_bytes(ctx.storage, sha)
    elif fmt == "pdf" and kind in ("docx", "pptx"):
        src = write_temp(ctx.storage, sha, f".{kind}")
        try:
            data = await run_sync(convert_to_pdf, src)
        finally:
            src.unlink(missing_ok=True)
    else:
        raise AppError(
            f"A {kind.upper()} file cannot be exported as {fmt.upper()}.", code="UNSUPPORTED_EXPORT", status_code=422
        )
    filename = f"{stem}{'' if number == 1 else f'.v{number}'}.{fmt}"
    async with ctx.sessionmaker() as s:
        blob = await store_bytes(s, ctx.storage, data, MIME_TYPES[fmt])
        exp = Export(
            owner_id=ctx.owner_id, version_id=uuid.UUID(params["version_id"]), format=fmt, blob=blob, filename=filename
        )
        s.add(exp)
        audit.record(
            s,
            "document.exported",
            owner_id=ctx.owner_id,
            subject_type="document_version",
            subject_id=uuid.UUID(params["version_id"]),
            format=fmt,
        )
        await s.commit()
        return {"export_id": str(exp.id), "filename": filename, "size_bytes": len(data)}
