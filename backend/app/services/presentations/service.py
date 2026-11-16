"""Presentation engine (Phase 7): build a themed PPTX deck from a document, an outline, or a brief.

* document → deterministic: one slide per section, key sentences as bullets, the section text
  as speaker notes (``domain.presentation.plan.from_document``).
* outline  → deterministic: the user's own '# slide / - bullet / > note' text.
* brief    → the configured language model proposes slides (needs the user's consent); it may not
  invent facts or sources, and the result is marked as AI-generated in the version summary.

Every deck goes through the same fitting step (font size from a fixed scale, at most six
bullets, overflow moved to "(cont.)" slides) and is then analysed like any upload, so the
inspection and slide checks run on the result.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from anyio.to_thread import run_sync

from app.adapters.formats.pptx_exporter import BODY_BOX, THEMES, TWO_COL_BOX, export_pptx
from app.adapters.llm import LLMUnavailable, get_provider
from app.core.errors import AppError
from app.db.models import Document, DocumentVersion, User
from app.domain.presentation.plan import Layout, SlideSpec, fit_slides, from_document, from_outline_text
from app.services import audit
from app.services.blobs import store_bytes
from app.services.jobs.runner import JobContext, handler
from app.services.processing.analysis import analyse
from app.services.versions import VersionService

PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
MAX_SLIDES = 40

SYSTEM = (
    "You are AKSHARA's presentation assistant. You plan clear slide decks for a human presenter who will "
    "review them. Rules: never invent facts, statistics, quotations, people, organisations, sources, DOIs or "
    "URLs. Use short bullet phrases (at most 12 words each, at most 5 per slide). Put supporting detail in "
    "speaker notes. If the brief lacks information a slide would need, say so in the notes instead of guessing."
)
DECK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "slides": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "layout": {"type": "string", "enum": ["title", "section", "bullets", "closing"]},
                    "title": {"type": "string"},
                    "bullets": {"type": "array", "items": {"type": "string"}},
                    "notes": {"type": "string"},
                },
                "required": ["layout", "title", "bullets", "notes"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["slides"],
    "additionalProperties": False,
}


def themes() -> list[dict[str, str]]:
    return [
        {"key": t.key, "label": t.label, "background": t.background, "title": t.title, "accent": t.accent}
        for t in THEMES.values()
    ]


def _deck_from_llm(data: dict[str, Any]) -> list[SlideSpec]:
    out: list[SlideSpec] = []
    for s in data.get("slides", [])[:MAX_SLIDES]:
        title = str(s.get("title", "")).strip()[:200]
        if not title:
            continue
        raw = s.get("layout")
        layout: Layout = raw if raw in ("title", "section", "bullets", "closing") else "bullets"
        bullets = [str(b).strip()[:300] for b in s.get("bullets", []) if str(b).strip()][:12]
        out.append(SlideSpec(layout, title, bullets=bullets, notes=str(s.get("notes", "")).strip()[:3000]))
    return out


def _safe(title: str) -> str:
    return re.sub(r"[^A-Za-z0-9 _-]+", "", title).strip()[:80] or "presentation"


@handler("presentation")
async def presentation_job(ctx: JobContext, params: dict[str, Any]) -> dict[str, Any]:
    source = params["source"]
    theme: str = params["theme"] if params.get("theme") in THEMES else "paper"
    author = ""
    llm_meta: dict[str, Any] | None = None
    async with ctx.sessionmaker() as s:
        user = await s.get(User, ctx.owner_id)
        if user is None:
            raise AppError("User not found.", code="USER_NOT_FOUND", status_code=404)
        author = user.display_name or ""
        if source == "document":
            adm = await VersionService(s, ctx.storage).adm(ctx.owner_id, uuid.UUID(params["version_id"]))
            plan = from_document(adm)
            author = ", ".join(adm.metadata.authors) or author
        elif source == "outline":
            plan = from_outline_text(params.get("outline", ""))
        elif source == "brief":
            provider = get_provider(ctx.settings.llm_provider, ctx.settings.llm_model)
            if provider is None:
                raise AppError("AI drafting is not configured on this server.", code="LLM_UNAVAILABLE", status_code=503)
            if not user.allow_external_llm:
                raise AppError(
                    "Allow external AI providers in Settings before using AI drafting.",
                    code="LLM_CONSENT_REQUIRED",
                    status_code=403,
                )
            n = int(params.get("slide_count") or 10)
            try:
                r = await provider.complete_json(
                    system=SYSTEM,
                    schema=DECK_SCHEMA,
                    prompt=(
                        f"Title: {params.get('title', '')}\nAudience: {params.get('audience', '')}\n"
                        f"Brief:\n{params.get('brief', '')}\n\nPlan a deck of about {n} slides: a title slide, "
                        "content slides, and a closing slide. Every slide needs speaker notes."
                    ),
                )
            except LLMUnavailable as exc:
                raise AppError(str(exc), code="LLM_UNAVAILABLE", status_code=503) from exc
            plan = _deck_from_llm(r.data)
            llm_meta = {"model": r.model, "input_tokens": r.input_tokens, "output_tokens": r.output_tokens}
            audit.record(s, "llm.call", owner_id=ctx.owner_id, purpose="presentation.brief", **llm_meta)
            await s.commit()
        else:
            raise AppError("Unknown presentation source.", code="BAD_SOURCE", status_code=422)
    if not plan:
        raise AppError("Nothing to put on slides — the source is empty.", code="EMPTY_DECK", status_code=422)
    title: str = str(params.get("title") or "").strip() or plan[0].title
    if plan[0].layout == "title":
        plan[0].title = title
    else:
        plan.insert(0, SlideSpec("title", title, subtitle=author))
    slides = fit_slides(plan[:MAX_SLIDES], BODY_BOX, TWO_COL_BOX)
    data = await run_sync(export_pptx, slides, theme, title, author)
    await ctx.progress(0.3)

    async with ctx.sessionmaker() as s:
        sha = await store_bytes(s, ctx.storage, data, PPTX_MIME)
        doc_id, ver_id = uuid.uuid4(), uuid.uuid4()
        s.add(
            Document(
                id=doc_id,
                owner_id=ctx.owner_id,
                title=title,
                original_filename=f"{_safe(title)}.pptx",
                kind="pptx",
                origin="generated",
                status="processing",
                safety_warnings=[],
            )
        )
        await s.flush()
        s.add(
            DocumentVersion(
                id=ver_id,
                document_id=doc_id,
                number=1,
                source_blob=sha,
                created_by="generation",
                summary={"analysis": "pending", "presentation": {"source": source, "theme": theme, "ai": llm_meta}},
            )
        )
        await s.flush()
        doc = await s.get(Document, doc_id)
        assert doc is not None
        doc.current_version_id = ver_id
        audit.record(
            s,
            "presentation.created",
            owner_id=ctx.owner_id,
            subject_type="document",
            subject_id=doc_id,
            source=source,
            theme=theme,
            slides=len(slides),
        )
        await s.commit()
    # Analyse in the same job so the deck opens already parsed, rendered and inspected.
    await analyse(ctx, {"version_id": str(ver_id)})
    return {"document_id": str(doc_id), "version_id": str(ver_id), "slides": len(slides)}
