from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from tests.conftest import register_and_login
from tests.fixtures.builders import KNOWN_DEFECTS

pytestmark = pytest.mark.integration


async def upload(client, headers, path: Path) -> dict:
    r = await client.post("/api/v1/documents", headers=headers, files={"file": (path.name, path.read_bytes())})
    assert r.status_code == 201, r.text
    return r.json()


async def test_inspection_runs_after_upload(client: httpx.AsyncClient, fixture_docs) -> None:
    headers = await register_and_login(client)
    doc = await upload(client, headers, fixture_docs["defective_docx"])
    vid = doc["current_version"]["id"]
    latest = (await client.get(f"/api/v1/versions/{vid}/inspections/latest", headers=headers)).json()
    found = {f["code"] for f in latest["findings"] if f["severity"] != "info"}
    assert found == KNOWN_DEFECTS
    scores = latest["stats"]["scores"]
    assert 0 <= scores["overall"] < 100 and set(scores["dimensions"]) == {
        "structure",
        "formatting",
        "references",
        "visual",
    }
    f = next(x for x in latest["findings"] if x["code"] == "STRUCT.HEADING_LEVEL_SKIP")
    assert f["severity"] == "high" and f["page_index"] == 0 and len(f["bbox"]) == 4

    # Dismiss a finding, then filter.
    r = await client.patch(
        f"/api/v1/findings/{f['id']}", headers=headers, json={"status": "dismissed", "reason": "intended"}
    )
    assert r.status_code == 200 and r.json()["status"] == "dismissed"
    still_open = (await client.get(f"/api/v1/inspections/{latest['id']}/findings?status=open", headers=headers)).json()
    assert f["id"] not in {x["id"] for x in still_open}

    # Re-run explicitly.
    r = await client.post(f"/api/v1/versions/{vid}/inspections", headers=headers)
    assert r.status_code == 202 and r.json()["status"] == "succeeded"


async def test_reports(client: httpx.AsyncClient, fixture_docs) -> None:
    headers = await register_and_login(client)
    vid = (await upload(client, headers, fixture_docs["defective_docx"]))["current_version"]["id"]
    run_id = (await client.get(f"/api/v1/versions/{vid}/inspections/latest", headers=headers)).json()["id"]
    html = await client.get(f"/api/v1/inspections/{run_id}/report?format=html", headers=headers)
    assert html.status_code == 200 and "Heading “1.1.1 Deep Detail” jumps" in html.text
    pdf = await client.get(f"/api/v1/inspections/{run_id}/report?format=pdf", headers=headers)
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
    js = (await client.get(f"/api/v1/inspections/{run_id}/report?format=json", headers=headers)).json()
    assert js["run"]["id"] == run_id and len(js["findings"]) >= len(KNOWN_DEFECTS)


async def test_quality_overview_and_isolation(client: httpx.AsyncClient, fixture_docs) -> None:
    alice = await register_and_login(client, "alice@example.com", "Alice-secret-1")
    await upload(client, alice, fixture_docs["clean_docx"])
    await upload(client, alice, fixture_docs["defective_docx"])
    q = (await client.get("/api/v1/quality", headers=alice)).json()
    by_title = {r["title"]: r["scores"]["overall"] for r in q}
    assert by_title["clean_report"] == 100.0 and by_title["defective_report"] < by_title["clean_report"]

    run_id = q[0]["run_id"]
    bob = await register_and_login(client, "bob@example.com", "Bob-secret-22")
    assert (await client.get("/api/v1/quality", headers=bob)).json() == []
    for path in (
        f"/api/v1/inspections/{run_id}",
        f"/api/v1/inspections/{run_id}/findings",
        f"/api/v1/inspections/{run_id}/report",
    ):
        assert (await client.get(path, headers=bob)).status_code == 404
