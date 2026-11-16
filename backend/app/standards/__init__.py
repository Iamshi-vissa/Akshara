"""Built-in standard profiles (data files). Each rule cites its source and verification level."""

from __future__ import annotations

import json
import uuid
from functools import lru_cache
from pathlib import Path

from app.domain.udse.schema import StandardProfile

BUILTIN_DIR = Path(__file__).parent / "builtin"
BUILTIN_NAMESPACE = uuid.UUID("6f2b0a8e-5d4c-4b7a-9c1e-0a1b2c3d4e5f")


def builtin_version_id(slug: str, version: str) -> uuid.UUID:
    """Stable id for a built-in profile version (built-ins live in files, not the database)."""
    return uuid.uuid5(BUILTIN_NAMESPACE, f"{slug}@{version}")


@lru_cache
def builtin_profiles() -> dict[str, StandardProfile]:
    out = {}
    for path in sorted(BUILTIN_DIR.glob("*.json")):
        profile = StandardProfile.model_validate(json.loads(path.read_text(encoding="utf-8")))
        out[profile.slug] = profile
    return out
