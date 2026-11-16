from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from tests.conftest import register_and_login

pytestmark = pytest.mark.integration


async def upload(client, headers, path: Path) -> dict:
    r = await client.post("/api/v1/documents", headers=headers, files={"file": (path.name, path.read_bytes())})
    assert r.status_code == 201, r.text
    return r.json()


def builtin_id(standards: list[dict], slug: str) -> str:
    return next(s for s in standards if s["slug"] == slug)["versions"][0]["id"]


async def test_builtins_listed_with_provenance(client: httpx.AsyncClient) -> None:
    headers = await register_and_login(client)
    stds = (await client.get("/api/v1/standards", headers=headers)).json()
    assert {s["slug"] for s in stds if s["builtin"]} == {"apa-7", "mla-9", "ieee-conference-letter"}
    detail = (await client.get(f"/api/v1/standard-versions/{builtin_id(stds, 'apa-7')}", headers=headers)).json()
    assert detail["builtin"] and detail["status"] == "published"
    assert all(r["provenance"]["source"] for r in detail["rules"])
    schema = (await client.get("/api/v1/udse/rule-schema", headers=headers)).json()
    assert "selector" in schema["properties"] and "check" in schema["properties"]


async def test_validate_against_apa(client: httpx.AsyncClient, fixture_docs) -> None:
    headers = await register_and_login(client)
    stds = (await client.get("/api/v1/standards", headers=headers)).json()
    apa = builtin_id(stds, "apa-7")
    doc = await upload(client, headers, fixture_docs["defective_docx"])
    vid = doc["current_version"]["id"]
    r = await client.post(f"/api/v1/versions/{vid}/validations", headers=headers, json={"standard_version_id": apa})
    assert r.status_code == 202 and r.json()["status"] == "succeeded", r.text
    run = (await client.get(f"/api/v1/versions/{vid}/inspections/latest?kind=udse", headers=headers)).json()
    comp = run["stats"]["compliance"]
    assert comp["verdict"] == "not compliant" and comp["score"] <= 69 and comp["hard_fail"] >= 4
    failed = {x["id"] for x in run["stats"]["rules"] if x["status"] == "fail"}
    assert {"page.margin.left", "typography.double_spacing", "page.page_numbers"} <= failed
    margin = next(f for f in run["findings"] if f["rule_id"] == "page.margin.left")
    assert margin["constraint_kind"] == "hard" and "0.5 in" in margin["message"]
    assert (await client.get(f"/api/v1/documents/{doc['id']}", headers=headers)).json()[
        "applied_standard_version_id"
    ] == apa
    pdf = await client.get(f"/api/v1/inspections/{run['id']}/report?format=pdf", headers=headers)
    assert pdf.content[:5] == b"%PDF-"


async def test_custom_standard_lifecycle(client: httpx.AsyncClient, fixture_docs) -> None:
    headers = await register_and_login(client)
    rule = {
        "id": "page.margin.left",
        "title": "University left margin",
        "category": "page",
        "kind": "hard",
        "severity": "high",
        "selector": {"node": "page_setup"},
        "check": {"op": "equals", "property": "margins.left", "value": 1.5, "unit": "in", "tolerance": 0.05},
    }
    r = await client.post(
        "/api/v1/standards",
        headers=headers,
        json={"name": "Example University Thesis", "extends": "apa-7", "rules": [rule]},
    )
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["status"] == "draft" and d["extends"] == "apa-7"
    merged = {x["id"]: x for x in d["rules"]}
    assert merged["page.margin.left"]["check"]["value"] == 1.5 and "typography.double_spacing" in merged

    bad = await client.put(
        f"/api/v1/standard-versions/{d['version_id']}/rules",
        headers=headers,
        json={"rules": [{**rule, "check": {"op": "llm_assess", "rubric": "x"}}]},
    )
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "INVALID_RULES"  # hard rules must be deterministic

    pub = (await client.post(f"/api/v1/standard-versions/{d['version_id']}/publish", headers=headers)).json()
    assert pub["status"] == "published"
    locked = await client.put(
        f"/api/v1/standard-versions/{d['version_id']}/rules", headers=headers, json={"rules": [rule]}
    )
    assert locked.status_code == 409  # published versions are immutable
    draft = (await client.post(f"/api/v1/standards/{d['standard_id']}/versions", headers=headers)).json()
    assert draft["status"] == "draft" and draft["version"] == "2"

    vid = (await upload(client, headers, fixture_docs["clean_docx"]))["current_version"]["id"]
    r = await client.post(
        f"/api/v1/versions/{vid}/validations", headers=headers, json={"standard_version_id": d["version_id"]}
    )
    assert r.json()["status"] == "succeeded"
    run = (await client.get(f"/api/v1/versions/{vid}/inspections/latest?kind=udse", headers=headers)).json()
    assert "page.margin.left" in {x["id"] for x in run["stats"]["rules"] if x["status"] == "fail"}  # 1 in ≠ 1.5 in

    dup = await client.post("/api/v1/standards", headers=headers, json={"name": "Example University Thesis"})
    assert dup.status_code == 409


async def test_standards_are_private(client: httpx.AsyncClient, fixture_docs) -> None:
    alice = await register_and_login(client, "alice@example.com", "Alice-secret-1")
    d = (await client.post("/api/v1/standards", headers=alice, json={"name": "Alice Rules", "extends": "mla-9"})).json()
    bob = await register_and_login(client, "bob@example.com", "Bob-secret-22")
    assert all(s["builtin"] for s in (await client.get("/api/v1/standards", headers=bob)).json())
    assert (await client.get(f"/api/v1/standard-versions/{d['version_id']}", headers=bob)).status_code == 404
    vid = (await upload(client, bob, fixture_docs["clean_docx"]))["current_version"]["id"]
    r = await client.post(
        f"/api/v1/versions/{vid}/validations", headers=bob, json={"standard_version_id": d["version_id"]}
    )
    assert r.status_code == 404
    assert (await client.delete(f"/api/v1/standards/{d['standard_id']}", headers=bob)).status_code == 404
