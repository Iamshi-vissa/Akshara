"""Client for a self-hosted LanguageTool server (grammar and spelling, decision D7)."""

from __future__ import annotations

from dataclasses import dataclass

import httpx


class GrammarUnavailable(Exception):
    pass


@dataclass
class GrammarMatch:
    offset: int
    length: int
    message: str
    replacement: str | None
    rule: str
    category: str


async def check(base_url: str, text: str, language: str = "auto") -> list[GrammarMatch]:
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
            r = await client.post("/v2/check", data={"text": text, "language": language})
            r.raise_for_status()
            payload = r.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise GrammarUnavailable("The grammar service could not be reached.") from exc
    out = []
    for m in payload.get("matches", []):
        reps = m.get("replacements") or []
        out.append(
            GrammarMatch(
                offset=m["offset"],
                length=m["length"],
                message=m.get("message", ""),
                replacement=reps[0]["value"] if reps else None,
                rule=m.get("rule", {}).get("id", ""),
                category=m.get("rule", {}).get("category", {}).get("id", ""),
            )
        )
    return out


def apply_matches(text: str, matches: list[GrammarMatch]) -> tuple[str, list[GrammarMatch]]:
    """Apply the first suggestion of each non-overlapping match (right to left).

    Adjacent grammar matches are usually *alternative* fixes for one error (LanguageTool flags
    "This are" both as "This → These" and "are → is"); applying both gives "These is". So when a
    grammar match ends right before an already-applied grammar match, it is skipped.
    """
    used: list[GrammarMatch] = []
    last_start = len(text) + 1
    last_grammar = False
    for m in sorted((m for m in matches if m.replacement is not None), key=lambda m: m.offset, reverse=True):
        if m.offset + m.length > last_start:
            continue
        is_grammar = m.category.upper() == "GRAMMAR"
        if is_grammar and last_grammar and last_start - (m.offset + m.length) <= 1:
            continue
        text = text[: m.offset] + (m.replacement or "") + text[m.offset + m.length :]
        last_start = m.offset
        last_grammar = is_grammar
        used.append(m)
    return text, list(reversed(used))
