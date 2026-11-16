"""Change sets: proposals that a person reviews, then applies as a new version.

Invariants (ARCHITECTURE.md §1.3):
* Nothing changes without a change set, and only *accepted* proposals are applied.
* Applying never touches the base version: the original file is patched into a *new* blob and
  a new version is created, then re-analysed, re-inspected and re-validated.
* A change set computed against an older version is stale and cannot be applied.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from anyio.to_thread import run_sync
from pydantic import TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import languagetool
from app.adapters.formats import apply_changes
from app.adapters.formats.docx_patcher import PatchError
from app.adapters.llm import LLMUnavailable, get_provider
from app.adapters.storage import BlobStorage
from app.core.config import Settings
from app.core.errors import AppError, ConflictError, NotFoundError
from app.db.models import (
    ChangeProposal,
    ChangeSet,
    Document,
    DocumentVersion,
    FindingRow,
    InspectionRun,
    User,
)
from app.domain.adm.model import AdmDocument, Caption, Heading, Paragraph
from app.domain.changes import DOCX_OPS, PPTX_OPS, Operation, Proposal, ReplaceText
from app.domain.correction import FindingRef, plan
from app.services import audit
from app.services.blobs import read_json, store_bytes, write_temp
from app.services.jobs.runner import JobContext, handler
from app.services.standards.service import StandardService

OPS = TypeAdapter(list[Operation])

AI_OPERATIONS: dict[str, str] = {
    "grammar": "Correct grammar, spelling and punctuation only. Change nothing else.",
    "clarity": "Improve clarity and readability. Keep every fact, claim, number and citation.",
    "paraphrase": "Paraphrase in different words with the same meaning, length and register.",
    "summarize": "Summarise into a shorter version that keeps the key claims, numbers and citations.",
    "expand": "Expand with more explanation of what is already said. Do not add new facts, data, sources or citations.",
    "academic": "Rewrite in a formal academic register. Keep every fact, number and citation.",
    "professional": "Rewrite in a clear, professional business register. Keep every fact and number.",
    "tone": "Rewrite in the requested tone. Keep every fact, number and citation.",
    "restructure": "Restructure the sentences for better flow. Keep the meaning and all facts.",
}
AI_SYSTEM = (
    "You are AKSHARA's editing assistant. You rewrite one paragraph at a time for a human editor who "
    "will review every change. Preserve the author's meaning. Never invent facts, data, quotations, "
    "sources, authors, DOIs or citations; keep existing citation markers such as [3] or (Smith, 2020) "
    "exactly as written. If the request cannot be done without changing the meaning, return the "
    "original text and say why in the notes."
)
AI_SCHEMA = {
    "type": "object",
    "properties": {
        "revised_text": {"type": "string"},
        "notes": {"type": "string"},
        "meaning_preserved": {"type": "boolean"},
    },
    "required": ["revised_text", "notes", "meaning_preserved"],
    "additionalProperties": False,
}


def _text_nodes(adm: AdmDocument) -> list[tuple[str, str]]:
    nodes: list[tuple[str, str]] = [
        (b.id, b.text)
        for b in adm.body
        if isinstance(b, Paragraph | Heading | Caption) and b.text.strip() and getattr(b, "role", "") != "empty"
    ]
    for s in adm.slides:
        for sh in s.shapes:
            nodes += [(p.id, p.text) for p in sh.paragraphs if p.text.strip()]
    return nodes


class ChangeService:
    def __init__(self, session: AsyncSession, storage: BlobStorage, settings: Settings) -> None:
        self.session = session
        self.storage = storage
        self.settings = settings

    # --- helpers --------------------------------------------------------------------------
    async def _current(
        self, owner_id: uuid.UUID, document_id: uuid.UUID
    ) -> tuple[Document, DocumentVersion, AdmDocument]:
        doc = await self.session.scalar(
            select(Document).where(
                Document.id == document_id, Document.owner_id == owner_id, Document.deleted_at.is_(None)
            )
        )
        if doc is None or doc.current_version_id is None:
            raise NotFoundError("Document not found.", code="DOCUMENT_NOT_FOUND")
        version = await self.session.get(DocumentVersion, doc.current_version_id)
        if version is None or version.adm_blob is None:
            raise AppError("Analyse the document before editing it.", code="NOT_ANALYSED", status_code=409)
        return doc, version, AdmDocument.model_validate(read_json(self.storage, version.adm_blob))

    def _supported(self, kind: str) -> set[str]:
        return DOCX_OPS if kind == "docx" else PPTX_OPS if kind == "pptx" else set()

    async def _persist(
        self,
        owner_id: uuid.UUID,
        doc: Document,
        version: DocumentVersion,
        source: str,
        items: list[tuple[Proposal, list[str], str]],
        summary: dict[str, Any],
    ) -> ChangeSet:
        supported = self._supported(doc.kind)
        cs = ChangeSet(
            owner_id=owner_id, document_id=doc.id, base_version_id=version.id, source=source, summary=summary
        )
        self.session.add(cs)
        await self.session.flush()
        manual = 0
        for i, (p, fids, origin) in enumerate(items):
            unsupported = [o.op for o in p.ops if o.op not in supported]
            if unsupported:
                manual += 1
                continue  # not applicable to this format: reported in the summary, never silently dropped
            self.session.add(
                ChangeProposal(
                    changeset_id=cs.id,
                    ordinal=i,
                    title=p.title,
                    rationale=p.rationale,
                    ops=[o.model_dump(mode="json") for o in p.ops],
                    risk=p.risk,
                    before=p.before,
                    after=p.after,
                    node_ids=p.node_ids,
                    finding_ids=fids,
                    rule_id=p.rule_id,
                    origin=origin,
                )
            )
        cs.summary = {**summary, "proposals": len(items) - manual, "manual_only": manual}
        if doc.kind == "pdf":
            cs.summary["note"] = "PDF files are reported only; corrections cannot be written into a PDF."
        audit.record(
            self.session,
            "changeset.created",
            owner_id=owner_id,
            subject_type="changeset",
            subject_id=cs.id,
            source=source,
            proposals=len(items) - manual,
        )
        await self.session.commit()
        return cs

    # --- builders -------------------------------------------------------------------------
    async def autocorrect(self, owner_id: uuid.UUID, document_id: uuid.UUID) -> ChangeSet:
        doc, version, adm = await self._current(owner_id, document_id)
        runs = (
            await self.session.scalars(
                select(InspectionRun)
                .where(InspectionRun.version_id == version.id, InspectionRun.owner_id == owner_id)
                .order_by(InspectionRun.created_at.desc())
            )
        ).all()
        latest: dict[str, InspectionRun] = {}
        for r in runs:
            latest.setdefault(r.kind, r)
        rules = {}
        family = None
        udse = latest.get("udse")
        if udse is not None and udse.standard_version_id:
            try:
                resolved = await StandardService(self.session).resolve(owner_id, udse.standard_version_id)
                rules = {r.id: r for r in resolved.profile.rules}
                family = resolved.profile.family
            except NotFoundError:
                pass
        run_ids = [r.id for r in latest.values()]
        rows = (
            (
                await self.session.scalars(
                    select(FindingRow)
                    .where(FindingRow.run_id.in_(run_ids), FindingRow.status == "open")
                    .order_by(FindingRow.ordinal)
                )
            ).all()
            if run_ids
            else []
        )
        refs = [
            FindingRef(
                id=str(f.id),
                code=f.code,
                node_ids=list(f.node_ids or []),
                expected=f.expected,
                actual=f.actual,
                rule_id=f.rule_id,
            )
            for f in rows
        ]
        planned = await run_sync(lambda: plan(adm, refs, rules, family))
        if not planned:
            raise AppError(
                "There is nothing AKSHARA can fix automatically in this version.",
                code="NOTHING_TO_FIX",
                status_code=422,
                details={"open_findings": len(rows)},
            )
        return await self._persist(
            owner_id,
            doc,
            version,
            "autocorrect",
            [(p.proposal, p.finding_ids, "deterministic") for p in planned],
            {"from_runs": [str(r) for r in run_ids], "standard": family},
        )

    async def manual(self, owner_id: uuid.UUID, document_id: uuid.UUID, edits: list[dict[str, str]]) -> ChangeSet:
        doc, version, adm = await self._current(owner_id, document_id)
        texts = dict(_text_nodes(adm))
        items: list[tuple[Proposal, list[str], str]] = []
        for e in edits:
            nid, after = e["node_id"], e["after"]
            if nid not in texts:
                raise AppError(f"Paragraph {nid} not found.", code="NODE_NOT_FOUND", status_code=422)
            if after.strip() == texts[nid].strip():
                continue
            items.append(
                (
                    Proposal(
                        title="Edit paragraph",
                        rationale="Edited by you.",
                        risk="content_change",
                        ops=[ReplaceText(node_id=nid, before=texts[nid], after=after)],
                        before=texts[nid],
                        after=after,
                        node_ids=[nid],
                    ),
                    [],
                    "user",
                )
            )
        if not items:
            raise AppError("No text was changed.", code="NOTHING_CHANGED", status_code=422)
        return await self._persist(owner_id, doc, version, "manual", items, {})

    async def grammar(self, owner_id: uuid.UUID, document_id: uuid.UUID, node_ids: list[str] | None) -> ChangeSet:
        if not self.settings.languagetool_url:
            raise AppError(
                "Grammar checking is not configured on this server.", code="GRAMMAR_UNAVAILABLE", status_code=503
            )
        doc, version, adm = await self._current(owner_id, document_id)
        nodes = [(n, t) for n, t in _text_nodes(adm) if not node_ids or n in node_ids][:400]
        lang = adm.metadata.language or "auto"
        items: list[tuple[Proposal, list[str], str]] = []
        for nid, text in nodes:
            try:
                matches = await languagetool.check(
                    self.settings.languagetool_url, text, lang if lang != "auto" else "auto"
                )
            except languagetool.GrammarUnavailable as exc:
                raise AppError(str(exc), code="GRAMMAR_UNAVAILABLE", status_code=503) from exc
            new, used = languagetool.apply_matches(text, matches)
            if used and new != text:
                items.append(
                    (
                        Proposal(
                            title=f"Grammar and spelling ({len(used)} fix{'es' if len(used) > 1 else ''})",
                            rationale="; ".join(m.message for m in used[:5]),
                            risk="content_change",
                            ops=[ReplaceText(node_id=nid, before=text, after=new)],
                            before=text,
                            after=new,
                            node_ids=[nid],
                        ),
                        [],
                        "grammar",
                    )
                )
        if not items:
            raise AppError("No grammar or spelling issues were found.", code="NOTHING_TO_FIX", status_code=422)
        return await self._persist(owner_id, doc, version, "grammar", items, {"checked_paragraphs": len(nodes)})

    async def ai_edit(
        self, owner_id: uuid.UUID, document_id: uuid.UUID, operation: str, node_ids: list[str], tone: str | None
    ) -> ChangeSet:
        provider = get_provider(self.settings.llm_provider, self.settings.llm_model)
        if provider is None:
            raise AppError("AI editing is not configured on this server.", code="LLM_UNAVAILABLE", status_code=503)
        user = await self.session.get(User, owner_id)
        if user is None or not user.allow_external_llm:
            raise AppError(
                "Allow external AI providers in Settings before using AI editing.",
                code="LLM_CONSENT_REQUIRED",
                status_code=403,
            )
        if operation not in AI_OPERATIONS:
            raise AppError("Unknown editing operation.", code="BAD_OPERATION", status_code=422)
        doc, version, adm = await self._current(owner_id, document_id)
        texts = dict(_text_nodes(adm))
        targets = [n for n in node_ids if n in texts][:20]
        if not targets:
            raise AppError("Select at least one paragraph.", code="NODE_NOT_FOUND", status_code=422)
        items: list[tuple[Proposal, list[str], str]] = []
        instruction = AI_OPERATIONS[operation] + (
            f" Requested tone: {tone[:60]}." if operation == "tone" and tone else ""
        )
        for nid in targets:
            try:
                result = await provider.complete_json(
                    system=AI_SYSTEM,
                    schema=AI_SCHEMA,
                    prompt=f"Task: {instruction}\n\n<paragraph>\n{texts[nid]}\n</paragraph>",
                )
            except LLMUnavailable as exc:
                raise AppError(str(exc), code="LLM_UNAVAILABLE", status_code=503) from exc
            revised = str(result.data.get("revised_text", "")).strip()
            if not revised or revised == texts[nid].strip():
                continue
            warn = (
                ""
                if result.data.get("meaning_preserved", False)
                else " The model reports the meaning may have changed."
            )
            items.append(
                (
                    Proposal(
                        title=f"AI {operation}",
                        risk="content_change",
                        rationale=f"Suggested by {result.model}. {result.data.get('notes', '')}{warn} Review before accepting.",
                        ops=[ReplaceText(node_id=nid, before=texts[nid], after=revised)],
                        before=texts[nid],
                        after=revised,
                        node_ids=[nid],
                    ),
                    [],
                    "llm",
                )
            )
            audit.record(
                self.session,
                "llm.call",
                owner_id=owner_id,
                purpose=f"edit.{operation}",
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )
        if not items:
            raise AppError("The assistant did not suggest any changes.", code="NOTHING_CHANGED", status_code=422)
        return await self._persist(owner_id, doc, version, "ai_edit", items, {"operation": operation})

    # --- review ---------------------------------------------------------------------------
    async def get(self, owner_id: uuid.UUID, changeset_id: uuid.UUID) -> tuple[ChangeSet, list[ChangeProposal]]:
        cs = await self.session.scalar(
            select(ChangeSet).where(ChangeSet.id == changeset_id, ChangeSet.owner_id == owner_id)
        )
        if cs is None:
            raise NotFoundError("Change set not found.", code="CHANGESET_NOT_FOUND")
        props = (
            await self.session.scalars(
                select(ChangeProposal).where(ChangeProposal.changeset_id == cs.id).order_by(ChangeProposal.ordinal)
            )
        ).all()
        return cs, list(props)

    async def decide(self, owner_id: uuid.UUID, changeset_id: uuid.UUID, decisions: dict[uuid.UUID, str]) -> None:
        cs, props = await self.get(owner_id, changeset_id)
        if cs.status != "open":
            raise ConflictError(f"This change set is {cs.status}.", code="CHANGESET_CLOSED")
        by_id = {p.id: p for p in props}
        now = datetime.now(UTC)
        for pid, decision in decisions.items():
            p = by_id.get(pid)
            if p is None:
                raise NotFoundError("Proposal not found.", code="PROPOSAL_NOT_FOUND")
            p.decision, p.decided_at = decision, now
        await self.session.commit()

    async def discard(self, owner_id: uuid.UUID, changeset_id: uuid.UUID) -> None:
        cs, _ = await self.get(owner_id, changeset_id)
        if cs.status == "open":
            cs.status = "discarded"
            await self.session.commit()

    async def list_for(self, owner_id: uuid.UUID, document_id: uuid.UUID) -> list[ChangeSet]:
        return list(
            (
                await self.session.scalars(
                    select(ChangeSet)
                    .where(ChangeSet.owner_id == owner_id, ChangeSet.document_id == document_id)
                    .order_by(ChangeSet.created_at.desc())
                    .limit(30)
                )
            ).all()
        )


async def _new_version(
    s: AsyncSession,
    doc: Document,
    parent: DocumentVersion,
    blob: str,
    created_by: str,
    changeset_id: uuid.UUID | None = None,
) -> DocumentVersion:
    number = (
        await s.scalar(select(func.max(DocumentVersion.number)).where(DocumentVersion.document_id == doc.id)) or 0
    ) + 1
    v = DocumentVersion(
        document_id=doc.id,
        number=number,
        parent_version_id=parent.id,
        source_blob=blob,
        created_by=created_by,
        summary={"analysis": "pending", "changeset_id": str(changeset_id) if changeset_id else None},
    )
    s.add(v)
    await s.flush()
    doc.current_version_id = v.id
    return v


async def _scores(s: AsyncSession, version_id: uuid.UUID) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for kind in ("inspection", "udse"):
        run = await s.scalar(
            select(InspectionRun)
            .where(InspectionRun.version_id == version_id, InspectionRun.kind == kind)
            .order_by(InspectionRun.created_at.desc())
            .limit(1)
        )
        if run is not None:
            out[kind] = (
                (run.stats.get("compliance") or {}).get("score")
                if kind == "udse"
                else (run.stats.get("scores") or {}).get("overall")
            )
            out[f"{kind}_findings"] = run.stats.get("total")
    return out


async def _analyse_and_validate(ctx: JobContext, version_id: uuid.UUID, standard_version_id: uuid.UUID | None) -> None:
    from app.services.processing.analysis import analyse
    from app.services.standards.service import run_validation

    await analyse(ctx, {"version_id": str(version_id)})
    if standard_version_id is not None:
        try:
            await run_validation(ctx, version_id, standard_version_id)
        except NotFoundError:
            pass  # the standard was deleted; the inspection result still stands


@handler("apply_changeset")
async def apply_changeset(ctx: JobContext, params: dict[str, Any]) -> dict[str, Any]:
    cs_id = uuid.UUID(params["changeset_id"])
    async with ctx.sessionmaker() as s:
        cs = await s.scalar(
            select(ChangeSet).where(ChangeSet.id == cs_id, ChangeSet.owner_id == ctx.owner_id).with_for_update()
        )
        if cs is None:
            raise NotFoundError("Change set not found.", code="CHANGESET_NOT_FOUND")
        doc = await s.get(Document, cs.document_id)
        base = await s.get(DocumentVersion, cs.base_version_id)
        if doc is None or base is None or base.adm_blob is None:
            raise NotFoundError("Document not found.", code="DOCUMENT_NOT_FOUND")
        if cs.status != "open":
            raise ConflictError(f"This change set is {cs.status}.", code="CHANGESET_CLOSED")
        if doc.current_version_id != base.id:
            cs.status = "stale"
            await s.commit()
            raise ConflictError(
                "The document changed after these proposals were made. Create new proposals.", code="CHANGESET_STALE"
            )
        props = (
            await s.scalars(
                select(ChangeProposal)
                .where(ChangeProposal.changeset_id == cs.id, ChangeProposal.decision == "accepted")
                .order_by(ChangeProposal.ordinal)
            )
        ).all()
        if not props:
            raise AppError("Accept at least one proposal before applying.", code="NOTHING_ACCEPTED", status_code=422)
        before_scores = await _scores(s, base.id)
        ops = OPS.validate_python([o for p in props for o in p.ops])
        adm = AdmDocument.model_validate(read_json(ctx.storage, base.adm_blob))
        kind, source_sha, finding_ids = (
            doc.kind,
            base.source_blob,
            [fid for p in props for fid in (p.finding_ids or [])],
        )
        standard_id = doc.applied_standard_version_id
        cs.status = "applying"
        await s.commit()

    src = write_temp(ctx.storage, source_sha, f".{kind}")
    try:
        try:
            patched = await run_sync(apply_changes, src, kind, adm, ops)
        except PatchError as exc:
            async with ctx.sessionmaker() as s:
                c = await s.get(ChangeSet, cs_id)
                if c is not None:
                    c.status, c.error_message = "failed", str(exc)
                    await s.commit()
            raise AppError(str(exc), code="PATCH_FAILED", status_code=422) from exc
    finally:
        src.unlink(missing_ok=True)

    async with ctx.sessionmaker() as s:
        doc2 = await s.get(Document, doc.id)
        base2 = await s.get(DocumentVersion, base.id)
        assert doc2 is not None and base2 is not None
        sha = await store_bytes(s, ctx.storage, patched, _mime(kind))
        new = await _new_version(s, doc2, base2, sha, "changeset", cs_id)
        c = await s.get(ChangeSet, cs_id)
        assert c is not None
        c.status, c.result_version_id, c.applied_at = "applied", new.id, datetime.now(UTC)
        for row in (
            await s.scalars(select(FindingRow).where(FindingRow.id.in_([uuid.UUID(f) for f in finding_ids])))
        ).all():
            row.status = "fixed"
        audit.record(
            s,
            "changeset.applied",
            owner_id=ctx.owner_id,
            subject_type="changeset",
            subject_id=cs_id,
            new_version=new.number,
            ops=len(ops),
        )
        await s.commit()
        new_id = new.id
    await ctx.progress(0.5)
    await _analyse_and_validate(ctx, new_id, standard_id)
    async with ctx.sessionmaker() as s:
        after_scores = await _scores(s, new_id)
        c = await s.get(ChangeSet, cs_id)
        if c is not None:
            c.summary = {**(c.summary or {}), "before": before_scores, "after": after_scores}
            await s.commit()
    return {"changeset_id": str(cs_id), "version_id": str(new_id), "before": before_scores, "after": after_scores}


@handler("revert")
async def revert(ctx: JobContext, params: dict[str, Any]) -> dict[str, Any]:
    """Restore an earlier version by creating a new version with its exact file. History is never rewritten."""
    async with ctx.sessionmaker() as s:
        target = await s.get(DocumentVersion, uuid.UUID(params["version_id"]))
        doc = await s.get(Document, target.document_id) if target else None
        if target is None or doc is None or doc.owner_id != ctx.owner_id:
            raise NotFoundError("Version not found.", code="VERSION_NOT_FOUND")
        current = await s.get(DocumentVersion, doc.current_version_id) if doc.current_version_id else None
        if current is not None and current.source_blob == target.source_blob:
            raise AppError("That version is already current.", code="ALREADY_CURRENT", status_code=409)
        new = await _new_version(s, doc, current or target, target.source_blob, "revert")
        audit.record(
            s,
            "document.reverted",
            owner_id=ctx.owner_id,
            subject_type="document",
            subject_id=doc.id,
            to_version=target.number,
            new_version=new.number,
        )
        await s.commit()
        new_id, standard_id = new.id, doc.applied_standard_version_id
    await _analyse_and_validate(ctx, new_id, standard_id)
    return {"version_id": str(new_id)}


def _mime(kind: str) -> str:
    from app.core.filesafety import MIME_TYPES

    return MIME_TYPES[kind]  # type: ignore[index]
