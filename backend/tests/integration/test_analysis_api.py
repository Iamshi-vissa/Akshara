"""Phase 2: real documents are parsed into the ADM and rendered into page images."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from tests.conftest import register_and_login

pytestmark = pytest.mark.integration


async def upload(client: httpx.AsyncClient, headers: dict[str, str], path: Path) -> dict:
    r = await client.post("/api/v1/documents", headers=headers, files={"file": (path.name, path.read_bytes())})
    assert r.status_code == 201, r.text
    return r.json()


async def test_docx_analysis_end_to_end(client: httpx.AsyncClient, fixture_docs: dict[str, Path]) -> None:
    headers = await register_and_login(client)
    doc = await upload(client, headers, fixture_docs["clean_docx"])
    assert doc["job_id"]
    v = doc["current_version"]
    assert v["analysis_status"] == "complete", v
    s = v["summary"]
    assert s["headings"] == 9 and s["tables"] == 1 and s["figures"] == 1 and s["captions"] == 2
    assert s["references"] == 2 and s["rendered_pages"] >= 1
    assert {
        "abstract",
        "introduction",
        "methodology",
        "results",
        "conclusion",
        "references",
    } <= set(s["sections_found"])

    job = (await client.get(f"/api/v1/jobs/{doc['job_id']}", headers=headers)).json()
    assert job["status"] == "succeeded" and job["type"] == "analyse" and job["progress"] == 1.0

    outline = (await client.get(f"/api/v1/versions/{v['id']}/outline", headers=headers)).json()
    assert outline[0]["level"] == 0 and outline[0]["text"].startswith("Quality Assurance")
    methodology = next(n for n in outline[0]["children"] if n["role"] == "methodology")
    assert [c["text"] for c in methodology["children"]] == ["2.1 Data Collection", "2.2 Analysis"]

    adm = (await client.get(f"/api/v1/versions/{v['id']}/adm", headers=headers)).json()
    assert adm["source_format"] == "docx"
    ps = adm["page_setups"][0]
    assert (ps["width_pt"], ps["height_pt"]) == (612.0, 792.0)
    assert ps["margins"] == {"top": 72.0, "bottom": 72.0, "left": 72.0, "right": 72.0}
    assert ps["footers"][0]["has_page_number"] is True
    body_para = next(b for b in adm["body"] if b["type"] == "paragraph" and b["role"] == "body")
    fmt = body_para["runs"][0]["fmt"]
    assert fmt["font_family"] == "Times New Roman" and fmt["size_pt"] == 12.0
    assert body_para["fmt"]["line_spacing"] == 2.0

    pages = (await client.get(f"/api/v1/versions/{v['id']}/pages", headers=headers)).json()
    assert len(pages) == s["rendered_pages"] and pages[0]["width_pt"] == 612.0
    img = await client.get(f"/api/v1/versions/{v['id']}/pages/0/image", headers=headers)
    assert img.status_code == 200 and img.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert (await client.get(f"/api/v1/versions/{v['id']}/pages/99/image", headers=headers)).status_code == 404


async def test_pdf_structure_is_inferred(client: httpx.AsyncClient, fixture_docs: dict[str, Path]) -> None:
    headers = await register_and_login(client)
    v = (await upload(client, headers, fixture_docs["defective_pdf"]))["current_version"]
    assert v["analysis_status"] == "complete"
    adm = (await client.get(f"/api/v1/versions/{v['id']}/adm", headers=headers)).json()
    heads = [
        ("".join(r["text"] for r in b["runs"]), b["level"], b["fidelity"])
        for b in adm["body"]
        if b["type"] == "heading"
    ]
    assert ("1.1.1 Deep Detail", 3, "inferred") in heads  # the planted level skip survives
    assert any("inferred" in w for w in adm["warnings"])


async def test_pptx_slides(client: httpx.AsyncClient, fixture_docs: dict[str, Path]) -> None:
    headers = await register_and_login(client)
    v = (await upload(client, headers, fixture_docs["clean_pptx"]))["current_version"]
    assert v["analysis_status"] == "complete" and v["summary"]["slides"] == 3
    outline = (await client.get(f"/api/v1/versions/{v['id']}/outline", headers=headers)).json()
    assert [n["text"] for n in outline] == ["Document Quality Review", "Goals", "Results"]
    adm = (await client.get(f"/api/v1/versions/{v['id']}/adm", headers=headers)).json()
    assert adm["slides"][1]["notes"] == "Speaker notes for Goals."
    pages = (await client.get(f"/api/v1/versions/{v['id']}/pages", headers=headers)).json()
    assert len(pages) == 3 and abs(pages[0]["width_pt"] - 960.0) < 0.5


async def test_reanalyse_and_isolation(client: httpx.AsyncClient, fixture_docs: dict[str, Path]) -> None:
    alice = await register_and_login(client, "alice@example.com", "Alice-secret-1")
    v = (await upload(client, alice, fixture_docs["clean_pptx"]))["current_version"]
    r = await client.post(f"/api/v1/versions/{v['id']}/analyse", headers=alice)
    assert r.status_code == 202 and r.json()["status"] == "succeeded"
    bob = await register_and_login(client, "bob@example.com", "Bob-secret-22")
    for path in ("adm", "outline", "pages", "pages/0/image"):
        assert (await client.get(f"/api/v1/versions/{v['id']}/{path}", headers=bob)).status_code == 404
    assert (await client.post(f"/api/v1/versions/{v['id']}/analyse", headers=bob)).status_code == 404
