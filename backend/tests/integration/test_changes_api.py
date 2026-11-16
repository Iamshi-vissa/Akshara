from __future__ import annotations

import hashlib
import os
from pathlib import Path

import httpx
import pytest

from tests.conftest import register_and_login

pytestmark = pytest.mark.integration
LT_URL = os.environ.get("AKSHARA_TEST_LANGUAGETOOL_URL", "http://localhost:8010")


async def upload(client, headers, path: Path) -> dict:
    r = await client.post("/api/v1/documents", headers=headers, files={"file": (path.name, path.read_bytes())})
    assert r.status_code == 201, r.text
    return r.json()


async def test_autocorrect_review_apply_revalidate(client: httpx.AsyncClient, fixture_docs) -> None:
    headers = await register_and_login(client)
    doc = await upload(client, headers, fixture_docs["defective_docx"])
    v1 = doc["current_version"]
    stds = (await client.get("/api/v1/standards", headers=headers)).json()
    apa = next(s for s in stds if s["slug"] == "apa-7")["versions"][0]["id"]
    await client.post(f"/api/v1/versions/{v1['id']}/validations", headers=headers, json={"standard_version_id": apa})

    cs = (
        await client.post(f"/api/v1/documents/{doc['id']}/changesets", headers=headers, json={"source": "autocorrect"})
    ).json()
    assert cs["status"] == "open" and len(cs["proposals"]) >= 8
    assert all(p["decision"] == "pending" for p in cs["proposals"])  # nothing pre-approved

    # Applying with nothing accepted is refused.
    assert (await client.post(f"/api/v1/changesets/{cs['id']}/apply", headers=headers)).status_code == 422

    keep = [p for p in cs["proposals"] if p["risk"] != "content_change"]
    reject = [p for p in cs["proposals"] if p["risk"] == "content_change"]
    body = {"decisions": {**{p["id"]: "accepted" for p in keep}, **{p["id"]: "rejected" for p in reject}}}
    assert (
        await client.post(f"/api/v1/changesets/{cs['id']}/decisions", headers=headers, json=body)
    ).status_code == 200
    job = (await client.post(f"/api/v1/changesets/{cs['id']}/apply", headers=headers)).json()
    assert job["status"] == "succeeded", job
    res = job["result"]
    assert res["after"]["udse"] > res["before"]["udse"] and res["after"]["inspection"] > res["before"]["inspection"]

    d = (await client.get(f"/api/v1/documents/{doc['id']}", headers=headers)).json()
    v2 = d["current_version"]
    assert v2["number"] == 2 and v2["created_by"] == "changeset" and v2["parent_version_id"] == v1["id"]
    assert v2["analysis_status"] == "complete" and v2["sha256"] != v1["sha256"]
    # The original is still downloadable byte-for-byte.
    orig = await client.get(f"/api/v1/versions/{v1['id']}/file", headers=headers)
    assert (
        hashlib.sha256(orig.content).hexdigest()
        == v1["sha256"]
        == hashlib.sha256(fixture_docs["defective_docx"].read_bytes()).hexdigest()
    )
    # Revalidation ran automatically against the applied standard.
    udse = (await client.get(f"/api/v1/versions/{v2['id']}/inspections/latest?kind=udse", headers=headers)).json()
    assert udse is not None and udse["stats"]["compliance"]["score"] == res["after"]["udse"]

    diff = (
        await client.get(
            f"/api/v1/documents/{doc['id']}/diff?from_version={v1['id']}&to_version={v2['id']}", headers=headers
        )
    ).json()
    assert diff["counts"]["format"] >= 1 and diff["page_setup"]

    # A second change set computed on v1 is now stale.
    assert (await client.post(f"/api/v1/changesets/{cs['id']}/apply", headers=headers)).status_code == 409

    # Revert creates v3 with v1's exact file.
    job = (
        await client.post(f"/api/v1/documents/{doc['id']}/revert", headers=headers, json={"version_id": v1["id"]})
    ).json()
    assert job["status"] == "succeeded"
    v3 = (await client.get(f"/api/v1/documents/{doc['id']}", headers=headers)).json()["current_version"]
    assert v3["number"] == 3 and v3["created_by"] == "revert" and v3["sha256"] == v1["sha256"]


async def test_stale_changeset(client: httpx.AsyncClient, fixture_docs) -> None:
    headers = await register_and_login(client)
    doc = await upload(client, headers, fixture_docs["defective_docx"])
    a = (
        await client.post(f"/api/v1/documents/{doc['id']}/changesets", headers=headers, json={"source": "autocorrect"})
    ).json()
    b = (
        await client.post(f"/api/v1/documents/{doc['id']}/changesets", headers=headers, json={"source": "autocorrect"})
    ).json()
    for cs in (a, b):
        await client.post(
            f"/api/v1/changesets/{cs['id']}/decisions",
            headers=headers,
            json={"decisions": {cs["proposals"][0]["id"]: "accepted"}},
        )
    assert (await client.post(f"/api/v1/changesets/{a['id']}/apply", headers=headers)).json()["status"] == "succeeded"
    r = await client.post(f"/api/v1/changesets/{b['id']}/apply", headers=headers)
    assert r.status_code == 409 and r.json()["error"]["code"] == "CHANGESET_STALE"
    assert (await client.get(f"/api/v1/changesets/{b['id']}", headers=headers)).json()["status"] == "stale"


async def test_manual_edit_and_rejection(client: httpx.AsyncClient, fixture_docs) -> None:
    headers = await register_and_login(client)
    doc = await upload(client, headers, fixture_docs["clean_docx"])
    adm = (await client.get(f"/api/v1/versions/{doc['current_version']['id']}/adm", headers=headers)).json()
    para = next(b for b in adm["body"] if b["type"] == "paragraph" and b["role"] == "body")
    cs = (
        await client.post(
            f"/api/v1/documents/{doc['id']}/changesets",
            headers=headers,
            json={"source": "manual", "edits": [{"node_id": para["id"], "after": "A rewritten paragraph."}]},
        )
    ).json()
    p = cs["proposals"][0]
    assert p["origin"] == "user" and p["after"] == "A rewritten paragraph."
    await client.post(
        f"/api/v1/changesets/{cs['id']}/decisions", headers=headers, json={"decisions": {p["id"]: "accepted"}}
    )
    assert (await client.post(f"/api/v1/changesets/{cs['id']}/apply", headers=headers)).json()["status"] == "succeeded"
    v2 = (await client.get(f"/api/v1/documents/{doc['id']}", headers=headers)).json()["current_version"]
    adm2 = (await client.get(f"/api/v1/versions/{v2['id']}/adm", headers=headers)).json()
    texts = ["".join(r["text"] for r in b.get("runs", [])) for b in adm2["body"]]
    assert "A rewritten paragraph." in texts


async def test_pdf_changesets_are_report_only(client: httpx.AsyncClient, fixture_docs) -> None:
    headers = await register_and_login(client)
    doc = await upload(client, headers, fixture_docs["defective_pdf"])
    cs = (
        await client.post(f"/api/v1/documents/{doc['id']}/changesets", headers=headers, json={"source": "autocorrect"})
    ).json()
    assert cs["proposals"] == [] and cs["summary"]["manual_only"] >= 1 and "PDF" in cs["summary"]["note"]


async def test_isolation(client: httpx.AsyncClient, fixture_docs) -> None:
    alice = await register_and_login(client, "alice@example.com", "Alice-secret-1")
    doc = await upload(client, alice, fixture_docs["defective_docx"])
    cs = (
        await client.post(f"/api/v1/documents/{doc['id']}/changesets", headers=alice, json={"source": "autocorrect"})
    ).json()
    bob = await register_and_login(client, "bob@example.com", "Bob-secret-22")
    assert (await client.get(f"/api/v1/changesets/{cs['id']}", headers=bob)).status_code == 404
    assert (await client.post(f"/api/v1/changesets/{cs['id']}/apply", headers=bob)).status_code == 404
    assert (
        await client.post(f"/api/v1/documents/{doc['id']}/changesets", headers=bob, json={"source": "autocorrect"})
    ).status_code == 404


async def test_ai_edit_requires_configuration_and_consent(client: httpx.AsyncClient, fixture_docs) -> None:
    headers = await register_and_login(client)
    doc = await upload(client, headers, fixture_docs["clean_docx"])
    r = await client.post(
        f"/api/v1/documents/{doc['id']}/changesets",
        headers=headers,
        json={"source": "ai_edit", "operation": "clarity", "node_ids": ["p2"]},
    )
    assert r.status_code == 503 and r.json()["error"]["code"] == "LLM_UNAVAILABLE"


async def test_ai_edit_with_test_provider(client: httpx.AsyncClient, fixture_docs, monkeypatch) -> None:
    """The provider is replaced by a deterministic stub in this test only (no network, no fake results in production)."""
    from app.adapters.llm import LLMResult
    from app.services.changes import service as svc

    class StubProvider:
        name = "stub"

        async def complete_json(self, *, system, prompt, schema, max_tokens=4000):
            assert "Never invent facts" in system and "<paragraph>" in prompt
            return LLMResult(
                data={"revised_text": "Clearer text.", "notes": "Shortened.", "meaning_preserved": True},
                model="stub-model",
                input_tokens=10,
                output_tokens=5,
            )

    monkeypatch.setattr(svc, "get_provider", lambda provider, model: StubProvider())
    headers = await register_and_login(client)
    doc = await upload(client, headers, fixture_docs["clean_docx"])
    adm = (await client.get(f"/api/v1/versions/{doc['current_version']['id']}/adm", headers=headers)).json()
    para = next(b for b in adm["body"] if b["type"] == "paragraph" and b["role"] == "body")
    body = {"source": "ai_edit", "operation": "clarity", "node_ids": [para["id"]]}
    r = await client.post(f"/api/v1/documents/{doc['id']}/changesets", headers=headers, json=body)
    assert r.status_code == 403 and r.json()["error"]["code"] == "LLM_CONSENT_REQUIRED"
    await client.patch("/api/v1/auth/me", headers=headers, json={"allow_external_llm": True})
    cs = (await client.post(f"/api/v1/documents/{doc['id']}/changesets", headers=headers, json=body)).json()
    p = cs["proposals"][0]
    assert p["origin"] == "llm" and p["after"] == "Clearer text." and p["decision"] == "pending"
    assert "stub-model" in p["rationale"]


def _lt_up() -> bool:
    try:
        return httpx.get(f"{LT_URL}/v2/languages", timeout=3).status_code == 200
    except httpx.HTTPError:
        return False


@pytest.mark.skipif(not _lt_up(), reason="LanguageTool server not reachable (set AKSHARA_TEST_LANGUAGETOOL_URL)")
async def test_grammar_with_real_languagetool(client: httpx.AsyncClient, fixture_docs, tmp_path) -> None:
    from docx import Document

    client.app.state.akshara.settings.languagetool_url = LT_URL  # type: ignore[attr-defined]
    path = tmp_path / "typos.docx"
    d = Document()
    d.add_paragraph("This are a sentence with a error in it.")
    d.add_paragraph("This sentence is fine.")
    d.save(str(path))
    headers = await register_and_login(client)
    doc = await upload(client, headers, path)
    cs = (
        await client.post(f"/api/v1/documents/{doc['id']}/changesets", headers=headers, json={"source": "grammar"})
    ).json()
    assert len(cs["proposals"]) == 1
    p = cs["proposals"][0]
    assert p["origin"] == "grammar" and "an error" in p["after"]
    assert "These is" not in p["after"]  # alternative fixes for one error are not combined
