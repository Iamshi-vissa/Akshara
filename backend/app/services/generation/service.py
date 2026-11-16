"""Outline-first document generation.

Works without a language model: templates give the outline, the user writes the content, and
AKSHARA formats and exports it (optionally to a standard). With a configured model and the
user's consent, the assistant can propose an outline and draft sections; every model-written
passage is marked ``generated`` and passes through the citation guard, which keeps only
citations to references the user supplied.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from anyio.to_thread import run_sync
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.formats.docx_exporter import export_docx
from app.adapters.llm import LLMProvider, LLMUnavailable, get_provider
from app.adapters.storage import BlobStorage
from app.core.config import Settings
from app.core.errors import AppError, NotFoundError
from app.db.models import Document, DocumentVersion, GenerationSession, User
from app.domain.adm.model import AdmDocument, Heading, Metadata, Paragraph, Run, Source
from app.domain.adm.outline import count_words
from app.domain.generation.citations import sanitize
from app.domain.generation.style import from_profile
from app.domain.generation.templates import KINDS, TONES, is_references, new_outline
from app.services import audit
from app.services.blobs import store_bytes
from app.services.jobs.runner import JobContext, handler
from app.services.standards.service import StandardService

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

SYSTEM = (
    "You are AKSHARA's drafting assistant. You write clear, well-structured professional prose for a "
    "human author who will review and edit it. Rules: never invent facts, statistics, quotations, people, "
    "organisations, sources, authors, publications, DOIs or URLs. Cite ONLY the numbered references you are "
    "given, as [n]; if no references are given, do not cite anything. Where a claim would need a source you "
    "do not have, write [citation needed]. Prefer general, verifiable statements over specific numbers."
)
OUTLINE_SCHEMA = {
    "type": "object",
    "properties": {
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "level": {"type": "integer"},
                    "target_words": {"type": "integer"},
                    "notes": {"type": "string"},
                },
                "required": ["title", "level", "target_words", "notes"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["sections"],
    "additionalProperties": False,
}
SECTION_SCHEMA = {
    "type": "object",
    "properties": {"paragraphs": {"type": "array", "items": {"type": "string"}}, "notes": {"type": "string"}},
    "required": ["paragraphs", "notes"],
    "additionalProperties": False,
}


def _clean_outline(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for it in items[:40]:
        title = str(it.get("title", "")).strip()[:200]
        if not title:
            continue
        out.append(
            {
                "id": str(it.get("id") or uuid.uuid4().hex[:10])[:16],
                "title": title,
                "level": min(max(int(it.get("level", 1)), 1), 3),
                "target_words": min(max(int(it.get("target_words", 0)), 0), 20000),
                "notes": str(it.get("notes", ""))[:1000],
            }
        )
    return out


class GenerationService:
    def __init__(self, session: AsyncSession, storage: BlobStorage, settings: Settings) -> None:
        self.session = session
        self.storage = storage
        self.settings = settings

    async def get(self, owner_id: uuid.UUID, session_id: uuid.UUID) -> GenerationSession:
        g = await self.session.scalar(
            select(GenerationSession).where(GenerationSession.id == session_id, GenerationSession.owner_id == owner_id)
        )
        if g is None:
            raise NotFoundError("Draft not found.", code="DRAFT_NOT_FOUND")
        return g

    async def list_drafts(self, owner_id: uuid.UUID) -> list[GenerationSession]:
        return list(
            (
                await self.session.scalars(
                    select(GenerationSession)
                    .where(GenerationSession.owner_id == owner_id)
                    .order_by(GenerationSession.updated_at.desc())
                    .limit(50)
                )
            ).all()
        )

    async def create(
        self,
        owner_id: uuid.UUID,
        *,
        kind: str,
        title: str,
        brief: dict[str, Any],
        references: list[str],
        standard_version_id: uuid.UUID | None,
    ) -> GenerationSession:
        if kind not in KINDS:
            raise AppError("Unknown document type.", code="BAD_KIND", status_code=422)
        if brief.get("tone") and brief["tone"] not in TONES:
            raise AppError("Unknown tone.", code="BAD_TONE", status_code=422)
        if standard_version_id:
            await StandardService(self.session).resolve(owner_id, standard_version_id)
        g = GenerationSession(
            owner_id=owner_id,
            kind=kind,
            title=title.strip()[:300],
            brief=brief,
            outline=new_outline(kind, brief.get("word_target")),
            references=[r.strip() for r in references if r.strip()][:200],
            standard_version_id=standard_version_id,
        )
        self.session.add(g)
        audit.record(self.session, "generation.created", owner_id=owner_id, kind=kind)
        await self.session.commit()
        await self.session.refresh(g)
        return g

    async def update(self, owner_id: uuid.UUID, session_id: uuid.UUID, changes: dict[str, Any]) -> GenerationSession:
        g = await self.get(owner_id, session_id)
        if g.status != "draft":
            raise AppError("This draft was already turned into a document.", code="DRAFT_FINALIZED", status_code=409)
        if changes.get("title"):
            g.title = str(changes["title"])[:300]
        if "outline" in changes:
            g.outline = _clean_outline(changes["outline"])
        if "references" in changes:
            g.references = [str(r).strip() for r in changes["references"] if str(r).strip()][:200]
        if "standard_version_id" in changes:
            sv = changes["standard_version_id"]
            if sv:
                await StandardService(self.session).resolve(owner_id, uuid.UUID(str(sv)))
            g.standard_version_id = uuid.UUID(str(sv)) if sv else None
        if "sections" in changes:
            sections = dict(g.sections or {})
            ids = {o["id"] for o in g.outline}
            for sid, text in (changes["sections"] or {}).items():
                if sid not in ids:
                    continue
                prev = sections.get(sid, {})
                text = str(text)[:200000]
                if text != prev.get("text"):
                    # Model-written text that a person changes becomes "edited"; never silently "user".
                    origin = "edited" if prev.get("origin") in ("generated", "edited") else "user"
                    sections[sid] = {**prev, "text": text, "origin": origin}
            g.sections = sections
        await self.session.commit()
        await self.session.refresh(g)
        return g

    async def _llm(self, owner_id: uuid.UUID) -> LLMProvider:
        provider = get_provider(self.settings.llm_provider, self.settings.llm_model)
        if provider is None:
            raise AppError("AI drafting is not configured on this server.", code="LLM_UNAVAILABLE", status_code=503)
        user = await self.session.get(User, owner_id)
        if user is None or not user.allow_external_llm:
            raise AppError(
                "Allow external AI providers in Settings before using AI drafting.",
                code="LLM_CONSENT_REQUIRED",
                status_code=403,
            )
        return provider

    def _context(self, g: GenerationSession) -> str:
        b = g.brief or {}
        refs = "\n".join(f"[{i}] {r}" for i, r in enumerate(g.references, start=1)) or "(none — do not cite anything)"
        return (
            f"Document type: {KINDS[g.kind]['label']}\nTitle: {g.title}\nTopic: {b.get('topic', '')}\n"
            f"Audience and instructions: {b.get('instructions', '')}\nTone: {b.get('tone', 'professional')}\n"
            f"References you may cite:\n{refs}"
        )

    async def ai_outline(self, owner_id: uuid.UUID, session_id: uuid.UUID) -> GenerationSession:
        g = await self.get(owner_id, session_id)
        provider = await self._llm(owner_id)
        total = int((g.brief or {}).get("word_target") or KINDS[g.kind]["words"])
        try:
            r = await provider.complete_json(
                system=SYSTEM,
                schema=OUTLINE_SCHEMA,
                prompt=(
                    f"{self._context(g)}\n\nPropose a section outline (levels 1-3) for about {total} words in total. "
                    "Give each section a target word count and a one-line note on what it should cover. "
                    "Include a References section only if references were given."
                ),
            )
        except LLMUnavailable as exc:
            raise AppError(str(exc), code="LLM_UNAVAILABLE", status_code=503) from exc
        outline = _clean_outline(r.data.get("sections", []))
        if not outline:
            raise AppError("The assistant did not return a usable outline.", code="LLM_EMPTY", status_code=502)
        g.outline, g.sections = outline, {}
        audit.record(
            self.session,
            "llm.call",
            owner_id=owner_id,
            purpose="generate.outline",
            model=r.model,
            input_tokens=r.input_tokens,
            output_tokens=r.output_tokens,
        )
        await self.session.commit()
        return g

    async def ai_section(self, owner_id: uuid.UUID, session_id: uuid.UUID, section_id: str) -> dict[str, Any]:
        g = await self.get(owner_id, session_id)
        sec = next((s for s in g.outline if s["id"] == section_id), None)
        if sec is None:
            raise NotFoundError("Section not found.", code="SECTION_NOT_FOUND")
        if is_references(sec["title"]):
            raise AppError(
                "The reference list is built from your references, not written by the assistant.",
                code="REFERENCES_SECTION",
                status_code=422,
            )
        provider = await self._llm(owner_id)
        outline_txt = "\n".join(f"{'  ' * (s['level'] - 1)}- {s['title']}" for s in g.outline)
        try:
            r = await provider.complete_json(
                system=SYSTEM,
                schema=SECTION_SCHEMA,
                max_tokens=8000,
                prompt=(
                    f"{self._context(g)}\n\nOutline:\n{outline_txt}\n\nWrite the section “{sec['title']}” "
                    f"({sec['notes'] or 'no extra notes'}). Aim for about {sec['target_words'] or 200} words, as paragraphs. "
                    "Do not repeat the heading."
                ),
            )
        except LLMUnavailable as exc:
            raise AppError(str(exc), code="LLM_UNAVAILABLE", status_code=503) from exc
        text = "\n\n".join(str(p).strip() for p in r.data.get("paragraphs", []) if str(p).strip())
        text, rep = sanitize(text, allowed=len(g.references))
        sections = dict(g.sections or {})
        sections[section_id] = {
            "text": text,
            "origin": "generated",
            "model": r.model,
            "citations_removed": rep.removed[:20],
            "notes": r.data.get("notes", ""),
        }
        g.sections = sections
        audit.record(
            self.session,
            "llm.call",
            owner_id=owner_id,
            purpose="generate.section",
            model=r.model,
            input_tokens=r.input_tokens,
            output_tokens=r.output_tokens,
        )
        await self.session.commit()
        result: dict[str, Any] = sections[section_id]
        return result

    def build_adm(self, g: GenerationSession, references_title: str) -> AdmDocument:
        src = Source(fmt="generated")
        body: list[Any] = [Heading(id="title", source=src, level=0, runs=[Run(text=g.title)])]
        author = (g.brief or {}).get("author")
        if author:
            body.append(Paragraph(id="author", source=src, role="author", runs=[Run(text=str(author))]))
        n = 0
        for s in g.outline:
            if is_references(s["title"]):
                if g.references:
                    body.append(
                        Heading(id=f"h-{s['id']}", source=src, level=s["level"], runs=[Run(text=references_title)])
                    )
                    refs = list(g.references)
                    if (g.brief or {}).get("citation_style") == "author_year":
                        # Author-date styles (APA, MLA) list entries alphabetically; numbered styles
                        # keep the user's order because the [n] markers depend on it.
                        refs.sort(key=lambda r: re.sub(r"[^a-z]", "", r.lower()))
                    for i, ref in enumerate(refs, start=1):
                        label = (
                            ref
                            if re.match(r"^\s*\[\d+\]", ref) or (g.brief or {}).get("citation_style") == "author_year"
                            else f"[{i}] {ref}"
                        )
                        body.append(
                            Paragraph(id=f"ref-{i}", source=src, role="reference_entry", runs=[Run(text=label)])
                        )
                continue
            content = (g.sections or {}).get(s["id"], {})
            text, origin = str(content.get("text", "")).strip(), content.get("origin", "user")
            adm_origin = {"generated": "generated", "edited": "edited"}.get(origin, "original")
            if not text:
                continue  # empty sections are left out rather than exported as placeholders
            body.append(Heading(id=f"h-{s['id']}", source=src, level=s["level"], runs=[Run(text=s["title"])]))
            for para in re.split(r"\n\s*\n", text):
                if para.strip():
                    n += 1
                    body.append(
                        Paragraph(
                            id=f"p{n}",
                            source=src,
                            origin=adm_origin,
                            runs=[Run(text=" ".join(para.split()))],
                        )
                    )
        words = sum(count_words(getattr(b, "text", "")) for b in body)
        return AdmDocument(
            source_format="generated",
            body=body,
            metadata=Metadata(title=g.title, authors=[str(author)] if author else [], word_count=words),
        )

    async def finalize(self, owner_id: uuid.UUID, session_id: uuid.UUID) -> tuple[Document, DocumentVersion]:
        g = await self.get(owner_id, session_id)
        if g.status != "draft":
            raise AppError("This draft was already turned into a document.", code="DRAFT_FINALIZED", status_code=409)
        if not any(str(v.get("text", "")).strip() for v in (g.sections or {}).values()):
            raise AppError("Write or draft at least one section first.", code="EMPTY_DRAFT", status_code=422)
        profile = (
            (await StandardService(self.session).resolve(owner_id, g.standard_version_id)).profile
            if g.standard_version_id
            else None
        )
        spec = from_profile(profile)
        adm = self.build_adm(g, spec.references_title)
        data = await run_sync(export_docx, adm, spec)
        sha = await store_bytes(self.session, self.storage, data, DOCX_MIME)
        doc_id, ver_id = uuid.uuid4(), uuid.uuid4()
        doc = Document(
            id=doc_id,
            owner_id=owner_id,
            title=g.title,
            original_filename=f"{_safe(g.title)}.docx",
            kind="docx",
            origin="generated",
            status="ready",
            safety_warnings=[],
            applied_standard_version_id=g.standard_version_id,
        )
        self.session.add(doc)
        await self.session.flush()
        generated = sum(1 for v in (g.sections or {}).values() if v.get("origin") == "generated")
        version = DocumentVersion(
            id=ver_id,
            document_id=doc_id,
            number=1,
            source_blob=sha,
            created_by="generation",
            summary={"analysis": "pending", "generated_sections": generated},
        )
        self.session.add(version)
        await self.session.flush()
        doc.current_version_id = ver_id
        g.status, g.document_id = "finalized", doc_id
        audit.record(
            self.session,
            "generation.finalized",
            owner_id=owner_id,
            subject_type="document",
            subject_id=doc_id,
            generated_sections=generated,
        )
        await self.session.commit()
        return doc, version


def _safe(title: str) -> str:
    return re.sub(r"[^A-Za-z0-9 _-]+", "", title).strip()[:80] or "document"


@handler("generate_outline")
async def outline_job(ctx: JobContext, params: dict[str, Any]) -> dict[str, Any]:
    async with ctx.sessionmaker() as s:
        g = await GenerationService(s, ctx.storage, ctx.settings).ai_outline(
            ctx.owner_id, uuid.UUID(params["session_id"])
        )
        return {"sections": len(g.outline)}


@handler("generate_section")
async def section_job(ctx: JobContext, params: dict[str, Any]) -> dict[str, Any]:
    async with ctx.sessionmaker() as s:
        out = await GenerationService(s, ctx.storage, ctx.settings).ai_section(
            ctx.owner_id, uuid.UUID(params["session_id"]), params["section_id"]
        )
        return {"words": count_words(out["text"]), "citations_removed": out.get("citations_removed", [])}
