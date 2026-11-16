"""Phase 2 pipeline: parse a version into the ADM and render its pages.

Results are stored as immutable blobs and linked from the version row. Parsing and rendering
are independent: a document that renders but cannot be parsed (or the reverse) keeps whatever
succeeded, and the version's ``analysis_status`` / ``summary.warnings`` say what is missing.
"""

from __future__ import annotations

import uuid
from typing import Any

from anyio.to_thread import run_sync
from sqlalchemy import delete, select

from app.adapters.formats import import_document
from app.adapters.render import RenderUnavailable, render_document
from app.core.errors import AppError, NotFoundError
from app.db.models import Document, DocumentVersion, RenderPage
from app.domain.adm.outline import summary
from app.services.blobs import store_bytes, store_json, write_temp
from app.services.jobs.runner import JobContext, handler


@handler("analyse")
async def analyse(ctx: JobContext, params: dict[str, Any]) -> dict[str, Any]:
    version_id = uuid.UUID(params["version_id"])
    async with ctx.sessionmaker() as s:
        row = (
            await s.execute(
                select(DocumentVersion, Document)
                .join(Document, Document.id == DocumentVersion.document_id)
                .where(DocumentVersion.id == version_id, Document.owner_id == ctx.owner_id)
            )
        ).first()
        if row is None:
            raise NotFoundError("Version not found.", code="VERSION_NOT_FOUND")
        version, doc = row
        version.analysis_status = "processing"
        doc.status = "processing"
        kind, source_sha = doc.kind, version.source_blob
        await s.commit()

    src = write_temp(ctx.storage, source_sha, f".{kind}")
    warnings: list[str] = []
    adm = None
    try:
        try:
            adm = await run_sync(import_document, src, kind)
        except Exception as exc:
            warnings.append(f"Structure could not be read: {type(exc).__name__}.")
        await ctx.progress(0.4)
        render = None
        try:
            render = await run_sync(render_document, src, kind)
        except RenderUnavailable as exc:
            warnings.append(str(exc))
        except Exception as exc:
            warnings.append(f"Pages could not be rendered: {exc}")
        await ctx.progress(0.8)
    finally:
        src.unlink(missing_ok=True)

    async with ctx.sessionmaker() as s:
        v = await s.get(DocumentVersion, version_id)
        d = await s.get(Document, v.document_id) if v else None
        if v is None or d is None:
            raise NotFoundError("Version not found.", code="VERSION_NOT_FOUND")
        version, doc = v, d
        info: dict[str, Any] = {"analysis": "failed"}
        if adm is not None:
            if render is not None and adm.metadata.page_count is None:
                adm.metadata.page_count = render.page_count
            version.adm_blob = await store_json(s, ctx.storage, adm.model_dump(mode="json"))
            version.adm_schema_version = adm.adm_schema_version
            info = summary(adm)
        await s.execute(delete(RenderPage).where(RenderPage.version_id == version_id))
        if render is not None:
            version.render_pdf_blob = await store_bytes(s, ctx.storage, render.pdf, "application/pdf")
            layout = {
                "renderer": render.renderer,
                "page_count": render.page_count,
                "truncated": render.truncated,
                "pages": [
                    {
                        "index": p.index,
                        "width_pt": p.width_pt,
                        "height_pt": p.height_pt,
                        "blank": p.blank,
                        "spans": p.spans,
                        "images": p.images,
                        "drawings_bbox": p.drawings_bbox,
                    }
                    for p in render.pages
                ],
            }
            version.layout_blob = await store_json(s, ctx.storage, layout)
            for p in render.pages:
                sha = await store_bytes(s, ctx.storage, p.png, "image/png")
                s.add(
                    RenderPage(
                        version_id=version_id,
                        page_index=p.index,
                        width_pt=p.width_pt,
                        height_pt=p.height_pt,
                        image_blob=sha,
                        blank=p.blank,
                    )
                )
            info["rendered_pages"] = len(render.pages)
            info["page_count"] = render.page_count
            if render.truncated:
                warnings.append(f"Only the first {len(render.pages)} pages were rendered.")
        info["warnings"] = [*info.get("warnings", []), *warnings]
        # Keep provenance written at creation time (generation / presentation); the rest is recomputed.
        kept = {k: v for k, v in (version.summary or {}).items() if k in ("generated_sections", "presentation")}
        version.summary = {**kept, **info}
        if adm is None and render is None:
            version.analysis_status, version.analysis_error = "failed", "; ".join(warnings)
        else:
            version.analysis_status, version.analysis_error = "complete", None
        doc.status = "ready"
        await s.commit()
        if version.analysis_status == "failed":
            raise AppError("The document could not be analysed: " + "; ".join(warnings), code="ANALYSIS_FAILED")
    # Inspect straight away so the workspace opens with findings (Phase 3), then re-validate
    # against the document's standard. Doing both here guarantees they run *after* parsing,
    # whatever executor is used (separately queued jobs could race the analysis).
    run_id = None
    if adm is not None:
        from app.services.inspections.service import run_inspection
        from app.services.standards.service import run_validation

        run_id = await run_inspection(ctx, version_id)
        async with ctx.sessionmaker() as s:
            v = await s.get(DocumentVersion, version_id)
            d = await s.get(Document, v.document_id) if v else None
            standard_id = d.applied_standard_version_id if d else None
        if standard_id is not None:
            try:
                await run_validation(ctx, version_id, standard_id)
            except NotFoundError:
                pass  # the standard was deleted; inspection results still stand
    return {
        "version_id": str(version_id),
        "summary": info,
        "inspection_run_id": str(run_id) if run_id else None,
    }
