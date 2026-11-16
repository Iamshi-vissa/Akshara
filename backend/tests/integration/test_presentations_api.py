from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from tests.conftest import register_and_login

pytestmark = pytest.mark.integration

OUTLINE = """# Document Quality at Scale
> Opening: why quality checks matter.
# The problem
- Reports are checked by hand, late and inconsistently
- Formatting rules differ per venue and are easy to miss
- Reviewers spend time on layout instead of content
> Each point has a slide of its own later.
## Approach
# What AKSHARA does
- Parses documents into one model
- Inspects structure, formatting, references and slides
- Proposes fixes that a person approves
- Exports a new version and keeps the original
- Re-checks the result against the chosen standard
- Shows a score with an explanation
- Works the same for DOCX, PDF and PPTX
- Never invents references
"""


async def _upload(client: httpx.AsyncClient, headers: dict[str, str], path: Path) -> dict:
    r = await client.post("/api/v1/documents", headers=headers, files={"file": (path.name, path.read_bytes())})
    assert r.status_code == 201, r.text
    return r.json()


async def _doc(client: httpx.AsyncClient, headers: dict[str, str], job: dict) -> dict:
    assert job["status"] == "succeeded", job
    r = await client.get(f"/api/v1/documents/{job['result']['document_id']}", headers=headers)
    assert r.status_code == 200
    return r.json()


async def test_themes(client: httpx.AsyncClient) -> None:
    headers = await register_and_login(client)
    themes = (await client.get("/api/v1/presentations/themes", headers=headers)).json()
    assert {t["key"] for t in themes} >= {"paper", "ink", "academic", "corporate"}


async def test_outline_to_validated_deck(client: httpx.AsyncClient) -> None:
    headers = await register_and_login(client)
    job = (
        await client.post(
            "/api/v1/presentations", headers=headers, json={"source": "outline", "outline": OUTLINE, "theme": "ink"}
        )
    ).json()
    doc = await _doc(client, headers, job)
    v = doc["current_version"]
    assert doc["kind"] == "pptx" and doc["origin"] == "generated" and v["created_by"] == "generation"
    assert v["analysis_status"] == "complete"
    assert v["summary"]["presentation"] == {"source": "outline", "theme": "ink", "ai": None}
    adm = (await client.get(f"/api/v1/versions/{v['id']}/adm", headers=headers)).json()
    titles = [s["title"] for s in adm["slides"]]
    # Eight bullets exceed the six-per-slide budget: overflow moves to a continuation slide.
    assert titles[0] == "Document Quality at Scale" and "What AKSHARA does (cont.)" in titles
    assert all(t for t in titles), "every slide has a real title placeholder"
    insp = (await client.get(f"/api/v1/versions/{v['id']}/inspections/latest", headers=headers)).json()
    codes = {f["code"] for f in insp["findings"]}
    assert not codes & {"SLIDE.MISSING_TITLE", "SLIDE.TEXT_OVERFLOW", "SLIDE.SMALL_FONT", "SLIDE.TOO_MUCH_TEXT"}, codes


async def test_document_to_deck(client: httpx.AsyncClient, fixture_docs: dict[str, Path]) -> None:
    headers = await register_and_login(client)
    src = (await _upload(client, headers, fixture_docs["clean_docx"]))["current_version"]
    job = (
        await client.post(
            "/api/v1/presentations",
            headers=headers,
            json={"source": "document", "version_id": src["id"], "theme": "academic"},
        )
    ).json()
    doc = await _doc(client, headers, job)
    adm = (await client.get(f"/api/v1/versions/{doc['current_version']['id']}/adm", headers=headers)).json()
    assert adm["slides"][-1]["title"] == "Questions?" and len(adm["slides"]) >= 4
    assert sum(1 for s in adm["slides"] if s["notes"].strip()) >= len(adm["slides"]) - 1


async def test_validation_and_privacy(client: httpx.AsyncClient, fixture_docs: dict[str, Path]) -> None:
    alice = await register_and_login(client, email="alice-p@example.com")
    bob = await register_and_login(client, email="bob-p@example.com")
    src = (await _upload(client, alice, fixture_docs["clean_docx"]))["current_version"]
    r = await client.post("/api/v1/presentations", headers=bob, json={"source": "document", "version_id": src["id"]})
    assert r.status_code == 404
    r = await client.post("/api/v1/presentations", headers=alice, json={"source": "outline", "outline": " "})
    assert r.status_code == 422
    r = await client.post(
        "/api/v1/presentations", headers=alice, json={"source": "outline", "outline": "# A", "theme": "neon"}
    )
    assert r.status_code == 422
    r = await client.post(
        "/api/v1/presentations", headers=alice, json={"source": "brief", "brief": "A talk about testing documents."}
    )
    assert r.status_code == 503 and r.json()["error"]["code"] == "LLM_UNAVAILABLE"


async def test_brief_uses_model_with_consent(client: httpx.AsyncClient, monkeypatch) -> None:
    from app.adapters.llm import LLMResult
    from app.api.v1 import presentations as api_mod
    from app.services.presentations import service as svc

    class Stub:
        name = "stub"

        async def complete_json(self, *, system, prompt, schema, max_tokens=4000):
            assert "never invent" in system.lower() and "testing documents" in prompt
            return LLMResult(
                data={
                    "slides": [
                        {"layout": "title", "title": "Testing Documents", "bullets": [], "notes": "Welcome."},
                        {"layout": "bullets", "title": "Why", "bullets": ["Fewer late fixes"], "notes": "Motivation."},
                        {"layout": "closing", "title": "Thanks", "bullets": [], "notes": "Questions."},
                    ]
                },
                model="stub-model",
                input_tokens=3,
                output_tokens=3,
            )

    monkeypatch.setattr(api_mod, "get_provider", lambda p, m: Stub())
    monkeypatch.setattr(svc, "get_provider", lambda p, m: Stub())
    headers = await register_and_login(client)
    body = {"source": "brief", "brief": "A short talk about testing documents.", "title": "Testing Documents"}
    r = await client.post("/api/v1/presentations", headers=headers, json=body)
    assert r.status_code == 403 and r.json()["error"]["code"] == "LLM_CONSENT_REQUIRED"
    await client.patch("/api/v1/auth/me", headers=headers, json={"allow_external_llm": True})
    job = (await client.post("/api/v1/presentations", headers=headers, json=body)).json()
    doc = await _doc(client, headers, job)
    assert doc["current_version"]["summary"]["presentation"]["ai"]["model"] == "stub-model"
