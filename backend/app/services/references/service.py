"""Reference verification (Phase 9).

For every entry in a version's reference list:

1. Read it as written (label, authors, year, title, DOI, URLs).
2. DOI given → look it up (Crossref, then OpenAlex). Unknown → "not found". Known → compare the
   title, year and first author with what the author wrote: "verified" or "mismatch".
3. No DOI → search Crossref by the text. Only a near-exact match is offered, as a *possible*
   match the user must confirm; otherwise the entry stays "unverified". Nothing is ever
   filled in from a guess.
4. Cited URLs → checked through the SSRF-safe checker.

Where a registry record exists, a correctly formatted version in the document's style is offered;
applying it goes through the normal approval-gated change flow (ChangeService.manual).
Results are stored as an inspection run of kind ``references``.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from app.adapters.scholarly import Registry, RegistryError
from app.adapters.urlcheck import check_url
from app.core.errors import AppError
from app.db.models import InspectionRun
from app.domain.adm.model import AdmDocument, Paragraph
from app.domain.inspection.model import Finding
from app.domain.references.format import STYLES, format_record
from app.domain.references.match import compare
from app.domain.references.model import Parsed, Record
from app.domain.references.parse import parse_reference
from app.domain.scoring import Scored, score
from app.services import audit
from app.services.inspections.service import finding_rows, load_inputs
from app.services.jobs.runner import JobContext, handler

ENGINE_VERSION = "references-1"
MAX_REFERENCES = 200
CONCURRENCY = 4
MATCH_THRESHOLD = 0.92  # title similarity for a search hit to be offered at all

# Seams for tests: replaced with recorded-response transports, never with invented results.
registry_factory = Registry
url_transport = None


def reference_entries(adm: AdmDocument) -> list[Paragraph]:
    return [b for b in adm.body if isinstance(b, Paragraph) and b.role == "reference_entry" and b.text.strip()]


def pick_style(requested: str | None, family: str | None, entries: list[Parsed]) -> str:
    if requested in STYLES:
        return requested
    if family in STYLES:
        return family
    numbered = sum(1 for e in entries if e.label.startswith("["))
    return "ieee" if entries and numbered >= len(entries) / 2 else "apa"


def _suggestion(rec: Record, style: str, label: str) -> str:
    text = format_record(rec, style)
    return f"{label} {text}".strip() if label else text


async def verify_entry(reg: Registry, p: Parsed, style: str) -> dict[str, Any]:
    item: dict[str, Any] = {"parsed": p.to_dict(), "status": "unverified", "record": None, "differences": []}
    try:
        if p.doi:
            rec = await reg.by_doi(p.doi)
            if rec is None:
                item["status"] = "not_found"
            else:
                c = compare(p, rec)
                bad = (p.title and c.title < 0.85) or c.year_ok is False or c.author_ok is False
                item.update(
                    status="mismatch" if bad else "verified",
                    record=rec.to_dict(),
                    differences=c.differences,
                    similarity=round(c.title, 3),
                    suggestion=_suggestion(rec, style, p.label),
                )
        elif p.title and len(p.title.split()) >= 3:
            best: tuple[float, Record] | None = None
            for rec in await reg.search(p.title, p.authors[0] if p.authors else "", p.year):
                c = compare(p, rec)
                # Offered only on positive evidence: title, first author and (if given) year agree.
                author_confirmed = c.author_ok is True or not p.authors
                year_confirmed = c.year_ok is True or p.year is None
                if c.title >= MATCH_THRESHOLD and author_confirmed and year_confirmed and rec.authors:
                    if best is None or c.score > best[0]:
                        best = (c.score, rec)
            if best:
                item.update(
                    status="possible_match",
                    record=best[1].to_dict(),
                    similarity=round(best[0], 3),
                    suggestion=_suggestion(best[1], style, p.label),
                )
    except RegistryError as exc:
        item.update(status="error", error=str(exc))
    urls = []
    for u in p.urls:
        r = await check_url(u, transport=url_transport)
        urls.append(
            {
                "url": u,
                "ok": r.ok,
                "checked": r.checked,
                "status": r.status,
                "reason": r.reason,
                "final_url": r.final_url,
            }
        )
    item["urls"] = urls
    return item


def findings_for(entry: Paragraph, item: dict[str, Any]) -> list[Finding]:
    p, status, rec = item["parsed"], item["status"], item.get("record") or {}
    where = f"Reference {p['label']}".strip() if p["label"] else "Reference"
    short = entry.text.strip()[:80] + ("…" if len(entry.text.strip()) > 80 else "")
    common: dict[str, Any] = {
        "category": "references",
        "node_ids": [entry.id],
        "location": where,
        "detector": "deterministic",
    }
    out: list[Finding] = []
    if status == "not_found":
        out.append(
            Finding(
                code="REF.DOI_NOT_FOUND",
                severity="high",
                message=f"The DOI {p['doi']} is not registered: {short}",
                explanation="Neither Crossref nor OpenAlex knows this DOI. It may be mistyped, or the reference may "
                "not exist as cited.",
                recommendation="Check the DOI against the publisher's page and correct or remove it.",
                actual=p["doi"],
                **common,
            )
        )
    elif status == "mismatch":
        out.append(
            Finding(
                code="REF.METADATA_MISMATCH",
                severity="medium",
                message="The reference does not match the record registered for its DOI "
                f"({'; '.join(item['differences'])}).",
                explanation="When the details differ from the DOI's registered record, either the DOI or the "
                "reference text is wrong.",
                recommendation="Compare with the registered record and correct whichever is wrong.",
                expected=rec.get("title"),
                actual=p["title"],
                fix_available=True,
                **common,
            )
        )
    elif status == "possible_match":
        out.append(
            Finding(
                code="REF.NO_DOI",
                severity="info",
                message=f"No DOI given; a registry record closely matches: {rec.get('doi')}",
                explanation="A DOI lets readers and reviewers find the exact work. This match was found by title "
                "search, so confirm it is the work you cited.",
                recommendation="If the match is right, add its DOI (apply the suggested reference).",
                expected=rec.get("doi"),
                confidence=0.8,
                fix_available=True,
                **common,
            )
        )
    elif status == "unverified" and not p["urls"]:
        out.append(
            Finding(
                code="REF.UNVERIFIED",
                severity="info",
                message=f"Could not be verified (no DOI or link, and no confident registry match): {short}",
                explanation="Unverifiable references are not necessarily wrong, but reviewers cannot check "
                "them easily.",
                recommendation="Add a DOI or a stable link if the work has one.",
                **common,
            )
        )
    for u in item.get("urls", []):
        if u["checked"] and not u["ok"]:
            out.append(
                Finding(
                    code="REF.URL_BROKEN",
                    severity="medium",
                    message=f"The link {u['url']} does not work ({u['reason']})",
                    explanation="Broken links stop readers from reaching the source.",
                    recommendation="Update the link, or cite an archived copy (e.g. the Wayback Machine).",
                    actual=u["url"],
                    **common,
                )
            )
    return out


@handler("verify_references")
async def verify_job(ctx: JobContext, params: dict[str, Any]) -> dict[str, Any]:
    version_id = uuid.UUID(params["version_id"])
    if not ctx.settings.reference_lookups:
        raise AppError("Reference lookups are turned off on this server.", code="LOOKUPS_DISABLED", status_code=503)
    async with ctx.sessionmaker() as s:
        _, doc, adm, _ = await load_inputs(s, ctx.storage, ctx.owner_id, version_id)
        family = None
        if doc.applied_standard_version_id:
            from app.services.standards.service import StandardService

            try:
                family = (
                    await StandardService(s).resolve(ctx.owner_id, doc.applied_standard_version_id)
                ).profile.family
            except AppError:
                family = None
    entries = reference_entries(adm)[:MAX_REFERENCES]
    if not entries:
        raise AppError("This document has no reference list to check.", code="NO_REFERENCES", status_code=422)
    parsed = [parse_reference(e.text) for e in entries]
    style = pick_style(params.get("style"), family, parsed)
    sem = asyncio.Semaphore(CONCURRENCY)
    done = 0

    async def one(reg: Registry, p: Parsed) -> dict[str, Any]:
        nonlocal done
        async with sem:
            r = await verify_entry(reg, p, style)
        done += 1
        if done % 5 == 0:
            await ctx.progress(done / len(parsed))
        return r

    async with registry_factory() as reg:
        items = await asyncio.gather(*(one(reg, p) for p in parsed))
    findings: list[Finding] = []
    for e, item in zip(entries, items, strict=True):
        item["node_id"] = e.id
        item["text"] = e.text
        findings.extend(findings_for(e, item))
    counts: dict[str, int] = {}
    for item in items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    errors = [{"check": "REF.LOOKUP", "reason": i["error"]} for i in items if i["status"] == "error"]
    stats = {
        "scores": score((Scored(f.category, f.severity, f.confidence) for f in findings), ("references",)),
        "items": items,
        "style": style,
        "counts": counts,
        "total": len(findings),
        "not_evaluated": errors[:20],
        "sources": ["Crossref", "OpenAlex"],
    }
    async with ctx.sessionmaker() as s:
        run = InspectionRun(
            owner_id=ctx.owner_id, version_id=version_id, kind="references", engine_version=ENGINE_VERSION, stats=stats
        )
        s.add(run)
        await s.flush()
        s.add_all(finding_rows(run.id, findings))
        audit.record(
            s,
            "references.verified",
            owner_id=ctx.owner_id,
            subject_type="document_version",
            subject_id=version_id,
            references=len(items),
            counts=counts,
        )
        await s.commit()
        return {"run_id": str(run.id), "references": len(items), "counts": counts, "style": style}
