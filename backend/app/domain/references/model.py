"""Bibliographic records (a small subset of CSL-JSON) and reference-check results."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Status = Literal["verified", "mismatch", "not_found", "possible_match", "unverified", "url_ok", "url_broken", "error"]


@dataclass
class Person:
    family: str
    given: str = ""


@dataclass
class Record:
    """What a registry (Crossref/OpenAlex) says about a work — never filled in by guesswork."""

    title: str
    authors: list[Person] = field(default_factory=list)
    year: int | None = None
    container: str = ""  # journal / proceedings / book series
    volume: str = ""
    issue: str = ""
    pages: str = ""
    publisher: str = ""
    doi: str = ""
    url: str = ""
    type: str = ""
    source: str = ""  # "crossref" | "openalex"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Parsed:
    """Fields read from the reference text as written by the author (heuristic)."""

    raw: str
    label: str = ""  # "[3]" or "3." when numbered
    authors: list[str] = field(default_factory=list)  # family names, in order
    year: int | None = None
    title: str = ""
    doi: str = ""
    urls: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
