from __future__ import annotations

import io

import httpx
import pytest
from docx import Document

from tests.conftest import register_and_login

pytestmark = pytest.mark.integration

GUIDELINE = [
    "Thesis Formatting Guidelines.",
    "All pages must use A4 paper. Use margins of 2.5 cm on all sides.",
    "The text must be 12-point Times New Roman and double-spaced.",
    "The abstract must not exceed 300 words. Number all pages.",
]


def _docx(paragraphs: list[str]) -> bytes:
    d = Document()
    for p in paragraphs:
        d.add_paragraph(p)
    out = io.BytesIO()
    d.save(out)
    return out.getvalue()


async def test_guideline_upload_to_reviewed_draft_standard(client: httpx.AsyncClient) -> None:
    headers = await register_and_login(client)
    r = await client.post(
        "/api/v1/standards/extract", headers=headers, files={"file": ("guide.docx", _docx(GUIDELINE))}
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["source_name"] == "guide.docx" and out["candidates"]
    source = " ".join(GUIDELINE)
    for c in out["candidates"]:  # every candidate is grounded in a verbatim quote from the file
        assert c["evidence_verified"] and c["quote"] in source and c["rule"]["provenance"]["quote"] == c["quote"]
    ids = {c["rule"]["id"] for c in out["candidates"]}
    assert {"page.paper", "page.margin.left", "typography.body_size"} <= ids

    # The reviewer accepts some candidates and rejects the rest; nothing was saved before this.
    assert [s for s in (await client.get("/api/v1/standards", headers=headers)).json() if not s["builtin"]] == []
    accepted = [c["rule"] for c in out["candidates"] if c["rule"]["id"] in ("page.paper", "typography.body_size")]
    st = (
        await client.post("/api/v1/standards", headers=headers, json={"name": "Thesis guide", "rules": accepted})
    ).json()
    assert st["status"] == "draft"
    assert {r["id"] for r in st["own_rules"]} == {"page.paper", "typography.body_size"}


async def test_extract_rejects_bad_input(client: httpx.AsyncClient) -> None:
    headers = await register_and_login(client)
    r = await client.post("/api/v1/standards/extract", headers=headers, data={"text": ""})
    assert r.status_code == 422 and r.json()["error"]["code"] == "NO_SOURCE"
    r = await client.post("/api/v1/standards/extract", headers=headers, files={"file": ("x.docx", b"not a zip")})
    assert r.status_code == 415
    r = await client.post(
        "/api/v1/standards/extract", headers=headers, data={"text": "The text must be 11-point Arial."}
    )
    assert r.status_code == 200 and r.json()["source_name"] == "Pasted text"
    r = await client.post("/api/v1/standards/extract", files={"file": ("guide.txt", b"x")})
    assert r.status_code == 401
