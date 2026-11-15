"""Store derived bytes (ADM JSON, page images, rendered PDFs) as immutable blobs."""

from __future__ import annotations

import gzip
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.storage import BlobStorage
from app.db.models import Blob


async def store_bytes(session: AsyncSession, storage: BlobStorage, data: bytes, mime: str) -> str:
    fd, name = tempfile.mkstemp(prefix="akshara-blob-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        stored = storage.put_file(Path(name))
    finally:
        os.unlink(name)
    await session.execute(
        pg_insert(Blob)
        .values(
            sha256=stored.sha256,
            size_bytes=stored.size_bytes,
            mime_type=mime,
            storage_key=stored.storage_key,
        )
        .on_conflict_do_nothing(index_elements=["sha256"])
    )
    return stored.sha256


async def store_json(session: AsyncSession, storage: BlobStorage, payload: Any) -> str:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    # mtime=0 keeps identical JSON byte-identical, so it deduplicates.
    return await store_bytes(session, storage, gzip.compress(raw, mtime=0), "application/gzip")


def read_bytes(storage: BlobStorage, sha: str) -> bytes:
    key = f"sha256/{sha[:2]}/{sha[2:4]}/{sha}"
    return b"".join(storage.open(key))


def read_json(storage: BlobStorage, sha: str) -> Any:
    return json.loads(gzip.decompress(read_bytes(storage, sha)))


def write_temp(storage: BlobStorage, sha: str, suffix: str) -> Path:
    """Materialise a blob as a private temp file (caller deletes it)."""
    fd, name = tempfile.mkstemp(prefix="akshara-src-", suffix=suffix)
    with os.fdopen(fd, "wb") as fh:
        fh.write(read_bytes(storage, sha))
    return Path(name)
