"""Record real registry responses once, then replay them in tests.

``python -m tests.fixtures.scholarly.replay record`` runs the reference fixture against the live
Crossref/OpenAlex/link endpoints and saves every exchange to ``recorded.json``. Tests use
:class:`ReplayTransport`, which serves those exact responses and fails on any request that was
not recorded — so no test can pass on invented data.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

RECORDED = Path(__file__).with_name("recorded.json")


def _key(request: httpx.Request) -> str:
    return f"{request.method} {request.url}"


class ReplayTransport(httpx.AsyncBaseTransport):
    def __init__(self, path: Path = RECORDED) -> None:
        self.data: dict[str, Any] = json.loads(path.read_text())

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        k = _key(request)
        if k not in self.data:
            raise AssertionError(f"Unrecorded request in test: {k}. Re-record the fixtures.")
        r = self.data[k]
        return httpx.Response(r["status"], headers=r["headers"], content=r["body"].encode(), request=request)


class RecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        self.inner = httpx.AsyncHTTPTransport(proxy=proxy, verify=os.environ.get("SSL_CERT_FILE", True))
        self.data: dict[str, Any] = {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        resp = await self.inner.handle_async_request(request)
        body = await resp.aread()
        keep = {k: v for k, v in resp.headers.items() if k.lower() in ("content-type", "location")}
        self.data[_key(request)] = {
            "status": resp.status_code,
            "headers": keep,
            "body": body.decode("utf-8", "replace"),
        }
        return httpx.Response(resp.status_code, headers=keep, content=body, request=request)


async def record() -> None:
    from app.adapters.scholarly import Registry
    from app.domain.references.parse import parse_reference
    from app.services.references import service as svc
    from tests.fixtures.builders import REFERENCE_ENTRIES

    rec = RecordingTransport()
    svc.url_transport = rec
    async with Registry(transport=rec) as reg:
        for e in REFERENCE_ENTRIES:
            item = await svc.verify_entry(reg, parse_reference(e), "ieee")
            print(item["parsed"]["label"], item["status"], [u["status"] for u in item["urls"]])
    RECORDED.write_text(json.dumps(rec.data, indent=1, sort_keys=True))
    print(f"recorded {len(rec.data)} exchanges → {RECORDED}")


if __name__ == "__main__":
    import asyncio
    import sys

    if sys.argv[1:] == ["record"]:
        asyncio.run(record())
