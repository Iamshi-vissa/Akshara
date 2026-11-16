from __future__ import annotations

import httpx
import pytest

from tests.conftest import register_and_login

pytestmark = pytest.mark.integration


async def apa_id(client, headers) -> str:
    stds = (await client.get("/api/v1/standards", headers=headers)).json()
    return next(s for s in stds if s["slug"] == "apa-7")["versions"][0]["id"]


PARA = (
    "Document quality depends on structure, consistent formatting and accurate references, and each of these "
    "can be checked systematically before a report is submitted for review."
)


async def test_manual_draft_to_compliant_document_and_export(client: httpx.AsyncClient) -> None:
    headers = await register_and_login(client)
    kinds = (await client.get("/api/v1/generation/kinds", headers=headers)).json()
    assert len(kinds) == 10
    d = (
        await client.post(
            "/api/v1/generation/drafts",
            headers=headers,
            json={
                "kind": "academic_report",
                "title": "Quality Checks for Student Reports",
                "topic": "document QA",
                "tone": "academic",
                "word_target": 1200,
                "author": "A. Student",
                "citation_style": "author_year",
                "references": [
                    "Writer, B. (2019). Structured writing. Example Press.",
                    "Author, A. (2020). Testing documents. Journal of Tests, 1(2), 1-10.",
                ],
                "standard_version_id": await apa_id(client, headers),
            },
        )
    ).json()
    assert d["status"] == "draft" and d["outline"][0]["title"] == "Abstract"
    sections = {s["id"]: f"{PARA}\n\n{PARA} (Writer, 2019)." for s in d["outline"] if s["title"] not in ("References",)}
    d = (
        await client.patch(f"/api/v1/generation/drafts/{d['id']}", headers=headers, json={"sections": sections})
    ).json()
    assert all(v["origin"] == "user" for v in d["sections"].values())

    doc = (await client.post(f"/api/v1/generation/drafts/{d['id']}/finalize", headers=headers)).json()
    assert doc["origin"] == "generated" and doc["kind"] == "docx"
    v = doc["current_version"]
    assert v["created_by"] == "generation" and v["analysis_status"] == "complete"
    udse = (await client.get(f"/api/v1/versions/{v['id']}/inspections/latest?kind=udse", headers=headers)).json()
    bad = [(r["id"], r["status"], r["reason"]) for r in udse["stats"]["rules"] if r["status"] == "fail"]
    assert udse["stats"]["compliance"]["verdict"] == "compliant", bad
    insp = (await client.get(f"/api/v1/versions/{v['id']}/inspections/latest", headers=headers)).json()
    assert not [f for f in insp["findings"] if f["severity"] in ("critical", "high")]

    job = (await client.post(f"/api/v1/versions/{v['id']}/exports", headers=headers, json={"format": "pdf"})).json()
    assert job["status"] == "succeeded", job
    pdf = await client.get(f"/api/v1/exports/{job['result']['export_id']}/file", headers=headers)
    assert pdf.content[:5] == b"%PDF-" and job["result"]["filename"].endswith(".pdf")

    again = await client.post(f"/api/v1/generation/drafts/{d['id']}/finalize", headers=headers)
    assert again.status_code == 409


async def test_ai_requires_configuration(client: httpx.AsyncClient) -> None:
    headers = await register_and_login(client)
    d = (
        await client.post("/api/v1/generation/drafts", headers=headers, json={"kind": "article", "title": "Hello"})
    ).json()
    job = (await client.post(f"/api/v1/generation/drafts/{d['id']}/outline", headers=headers)).json()
    assert job["status"] == "failed" and job["error_code"] == "LLM_UNAVAILABLE"
    assert (await client.post(f"/api/v1/generation/drafts/{d['id']}/finalize", headers=headers)).status_code == 422


async def test_ai_section_citations_are_guarded(client: httpx.AsyncClient, monkeypatch) -> None:
    from app.adapters.llm import LLMResult
    from app.services.generation import service as gen

    class Stub:
        name = "stub"

        async def complete_json(self, *, system, prompt, schema, max_tokens=4000):
            assert "never invent" in system.lower() and "[1] Writer" in prompt
            return LLMResult(
                data={"paragraphs": ["Known work [1].", "Invented work [7] and (Doe, 2021)."], "notes": ""},
                model="stub-model",
                input_tokens=5,
                output_tokens=5,
            )

    monkeypatch.setattr(gen, "get_provider", lambda p, m: Stub())
    headers = await register_and_login(client)
    await client.patch("/api/v1/auth/me", headers=headers, json={"allow_external_llm": True})
    d = (
        await client.post(
            "/api/v1/generation/drafts",
            headers=headers,
            json={"kind": "article", "title": "Guarded", "references": ["Writer, B. (2019). Structured writing."]},
        )
    ).json()
    sid = d["outline"][0]["id"]
    job = (await client.post(f"/api/v1/generation/drafts/{d['id']}/sections/{sid}/generate", headers=headers)).json()
    assert job["status"] == "succeeded" and set(job["result"]["citations_removed"]) == {"[7]", "(Doe, 2021)"}
    d = (await client.get(f"/api/v1/generation/drafts/{d['id']}", headers=headers)).json()
    sec = d["sections"][sid]
    assert sec["origin"] == "generated" and "[1]" in sec["text"] and "[citation needed]" in sec["text"]
    # Editing a generated section marks it "edited", not "user".
    d = (
        await client.patch(
            f"/api/v1/generation/drafts/{d['id']}", headers=headers, json={"sections": {sid: sec["text"] + " More."}}
        )
    ).json()
    assert d["sections"][sid]["origin"] == "edited"


async def test_drafts_are_private(client: httpx.AsyncClient) -> None:
    alice = await register_and_login(client, "alice@example.com", "Alice-secret-1")
    d = (await client.post("/api/v1/generation/drafts", headers=alice, json={"kind": "essay", "title": "Mine"})).json()
    bob = await register_and_login(client, "bob@example.com", "Bob-secret-22")
    assert (await client.get(f"/api/v1/generation/drafts/{d['id']}", headers=bob)).status_code == 404
    assert (await client.get("/api/v1/generation/drafts", headers=bob)).json() == []
