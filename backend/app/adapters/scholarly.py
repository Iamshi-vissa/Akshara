"""Bibliographic registries: Crossref (primary) and OpenAlex (fallback).

Only public bibliographic data is sent (a DOI, or a reference's title/authors for a search).
No user identifiers go to either service; requests use a generic client name. Responses are
normalised into :class:`Record`; nothing is ever invented — a field the registry does not
return stays empty.
"""

from __future__ import annotations

import asyncio
import html
import re
from typing import Any
from urllib.parse import quote

import httpx

from app.domain.references.model import Person, Record

USER_AGENT = "AKSHARA/1.0 (reference verification)"
CROSSREF = "https://api.crossref.org"
OPENALEX = "https://api.openalex.org"
TIMEOUT = httpx.Timeout(15.0, connect=8.0)
RETRIES = 2
MAX_WAIT = 5.0


class RegistryError(Exception):
    """The registry could not be reached or answered with an error (not "not found")."""


def _text(v: Any) -> str:
    if isinstance(v, list):
        v = v[0] if v else ""
    s = html.unescape(str(v or ""))
    return " ".join(re.sub(r"<[^>]+>", " ", s).split())


def from_crossref(m: dict[str, Any]) -> Record:
    title = _text(m.get("title"))
    sub = _text(m.get("subtitle"))
    if sub and sub.lower() not in title.lower():
        title = f"{title}: {sub}"
    year = None
    for key in ("issued", "published", "published-print", "published-online"):
        parts = (m.get(key) or {}).get("date-parts") or [[None]]
        if parts and parts[0] and parts[0][0]:
            year = int(parts[0][0])
            break
    authors = [
        Person(family=_text(a.get("family") or a.get("name")), given=_text(a.get("given")))
        for a in m.get("author", [])
        if a.get("family") or a.get("name")
    ]
    return Record(
        title=title,
        authors=authors,
        year=year,
        container=_text(m.get("container-title")),
        volume=_text(m.get("volume")),
        issue=_text(m.get("issue")),
        pages=_text(m.get("page")),
        publisher=_text(m.get("publisher")),
        doi=str(m.get("DOI", "")).lower(),
        url=str(m.get("URL", "")),
        type=str(m.get("type", "")),
        source="crossref",
    )


def from_openalex(w: dict[str, Any]) -> Record:
    authors = []
    for a in w.get("authorships", []):
        name = _text((a.get("author") or {}).get("display_name"))
        if name:
            given, _, family = name.rpartition(" ")
            authors.append(Person(family=family or name, given=given))
    loc = w.get("primary_location") or {}
    biblio = w.get("biblio") or {}
    first, last = biblio.get("first_page"), biblio.get("last_page")
    pages = f"{first}-{last}" if first and last and first != last else str(first or "")
    doi = str(w.get("doi") or "").lower().removeprefix("https://doi.org/")
    return Record(
        title=_text(w.get("title") or w.get("display_name")),
        authors=authors,
        year=w.get("publication_year"),
        container=_text((loc.get("source") or {}).get("display_name")),
        volume=_text(biblio.get("volume")),
        issue=_text(biblio.get("issue")),
        pages=pages,
        doi=doi,
        url=str(w.get("id", "")),
        type=str(w.get("type", "")),
        source="openalex",
    )


class Registry:
    """Async client; pass ``transport`` to replay recorded responses in tests."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=TIMEOUT,
            transport=transport,
            follow_redirects=True,
        )

    async def __aenter__(self) -> Registry:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.aclose()

    async def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        for attempt in range(RETRIES + 1):
            try:
                r = await self._client.get(url, params=params)
            except httpx.HTTPError as exc:
                raise RegistryError(f"{httpx.URL(url).host} could not be reached ({type(exc).__name__}).") from exc
            if r.status_code not in (429, 503) or attempt == RETRIES:
                break
            # Rate limited: honour Retry-After (capped) and try again.
            try:
                wait = min(float(r.headers.get("retry-after", "")), MAX_WAIT)
            except ValueError:
                wait = 1.0 * (attempt + 1)
            await asyncio.sleep(max(wait, 0.5))
        if r.status_code == 404:
            return None
        if r.status_code >= 400:
            raise RegistryError(f"{httpx.URL(url).host} answered HTTP {r.status_code}.")
        try:
            data: dict[str, Any] = r.json()
        except ValueError as exc:
            raise RegistryError(f"{httpx.URL(url).host} returned an unreadable response.") from exc
        return data

    async def by_doi(self, doi: str) -> Record | None:
        """The record registered for ``doi``; ``None`` when neither registry knows it."""
        crossref_error: RegistryError | None = None
        try:
            data = await self._get(f"{CROSSREF}/works/{quote(doi, safe='/')}")
            if data and data.get("message"):
                return from_crossref(data["message"])
        except RegistryError as exc:
            crossref_error = exc
        # Not every DOI is a Crossref DOI (e.g. DataCite); OpenAlex covers many of the others.
        data = await self._get(f"{OPENALEX}/works/doi:{quote(doi, safe='/')}")
        if data and data.get("id"):
            return from_openalex(data)
        if crossref_error:
            raise crossref_error
        return None

    async def search(self, title: str, author: str = "", year: int | None = None, rows: int = 5) -> list[Record]:
        params: dict[str, Any] = {"query.bibliographic": f"{title} {year or ''}".strip()[:300]}
        if author:
            params["query.author"] = author[:100]
        data = await self._get(
            f"{CROSSREF}/works",
            params={
                **params,
                "rows": rows,
                "select": "DOI,title,subtitle,author,issued,container-title,type,volume,issue,page,publisher,URL",
            },
        )
        items = ((data or {}).get("message") or {}).get("items") or []
        return [from_crossref(m) for m in items]
