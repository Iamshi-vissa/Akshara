from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from tests.conftest import register_and_login
from tests.fixtures.builders import REFERENCE_CASES

pytestmark = pytest.mark.integration


@pytest.fixture
def replay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Serve recorded Crossref/OpenAlex/link responses; unrecorded requests fail the test."""
    from app.adapters.scholarly import Registry
    from app.services.references import service as svc
    from tests.fixtures.scholarly.replay import ReplayTransport

    t = ReplayTransport()
    monkeypatch.setattr(svc, "registry_factory", lambda: Registry(transport=t))
    monkeypatch.setattr(svc, "url_transport", t)


async def _upload(client: httpx.AsyncClient, headers: dict[str, str], path: Path) -> dict:
    r = await client.post("/api/v1/documents", headers=headers, files={"file": (path.name, path.read_bytes())})
    assert r.status_code == 201, r.text
    return r.json()


async def test_verify_and_correct_references(client: httpx.AsyncClient, fixture_docs, replay) -> None:
    headers = await register_and_login(client)
    doc = await _upload(client, headers, fixture_docs["references_docx"])
    vid = doc["current_version"]["id"]
    job = (await client.post(f"/api/v1/versions/{vid}/references/verify", headers=headers, json={})).json()
    assert job["status"] == "succeeded", job
    assert job["result"]["style"] == "ieee"  # numbered [n] entries

    run = (await client.get(f"/api/v1/versions/{vid}/inspections/latest?kind=references", headers=headers)).json()
    items = run["stats"]["items"]
    assert {i["parsed"]["label"]: i["status"] for i in items} == REFERENCE_CASES
    codes = sorted(f["code"] for f in run["findings"])
    assert codes == ["REF.DOI_NOT_FOUND", "REF.DOI_NOT_FOUND", "REF.METADATA_MISMATCH", "REF.NO_DOI", "REF.UNVERIFIED"]
    assert run["stats"]["scores"]["dimensions"]["references"] < 100

    # Apply the registry-based correction for [3] through the normal approval-gated flow.
    wrong = next(i for i in items if i["parsed"]["label"] == "[3]")
    assert '"Deep learning,"' in wrong["suggestion"] and wrong["record"]["doi"] == "10.1038/nature14539"
    cs = (
        await client.post(
            f"/api/v1/documents/{doc['id']}/changesets",
            headers=headers,
            json={
                "source": "manual",
                "edits": [{"node_id": wrong["node_id"], "after": wrong["suggestion"].replace("*", "")}],
            },
        )
    ).json()
    pid = cs["proposals"][0]["id"]
    await client.post(
        f"/api/v1/changesets/{cs['id']}/decisions", headers=headers, json={"decisions": {pid: "accepted"}}
    )
    job = (await client.post(f"/api/v1/changesets/{cs['id']}/apply", headers=headers)).json()
    assert job["status"] == "succeeded", job
    doc2 = (await client.get(f"/api/v1/documents/{doc['id']}", headers=headers)).json()
    assert doc2["current_version"]["number"] == 2
    adm = (await client.get(f"/api/v1/versions/{doc2['current_version']['id']}/adm", headers=headers)).json()
    texts = ["".join(r["text"] for r in b.get("runs", [])) for b in adm["body"]]
    assert any(t.startswith('[3] Y. LeCun, Y. Bengio, and G. Hinton, "Deep learning,"') for t in texts)


async def test_lookups_can_be_disabled_and_need_a_reference_list(
    client: httpx.AsyncClient, fixture_docs, settings
) -> None:
    headers = await register_and_login(client)
    vid = (await _upload(client, headers, fixture_docs["visual_docx"]))["current_version"]["id"]
    job = (await client.post(f"/api/v1/versions/{vid}/references/verify", headers=headers, json={})).json()
    assert job["status"] == "failed" and job["error_code"] == "NO_REFERENCES"
    settings.reference_lookups = False
    try:
        r = await client.post(f"/api/v1/versions/{vid}/references/verify", headers=headers, json={})
        assert r.status_code == 503 and r.json()["error"]["code"] == "LOOKUPS_DISABLED"
    finally:
        settings.reference_lookups = True


@pytest.mark.skipif(
    os.environ.get("AKSHARA_TEST_NETWORK") != "1", reason="live registry check (AKSHARA_TEST_NETWORK=1)"
)
async def test_live_registries_agree_with_recording() -> None:
    from app.adapters.scholarly import Registry

    async with Registry() as reg:
        rec = await reg.by_doi("10.1145/3292500.3330701")
        assert rec is not None and rec.year == 2019 and rec.authors[0].family == "Akiba"
        assert await reg.by_doi("10.9999/akshara-does-not-exist-123") is None
