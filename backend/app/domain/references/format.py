"""Format a registry record in a citation style (APA 7, IEEE, MLA 9).

A deliberately small subset of CSL: journal articles, conference papers, books and chapters.
Only fields present in the record are printed — nothing is filled in.
"""

from __future__ import annotations

from collections.abc import Callable

from app.domain.references.model import Person, Record

STYLES = ("apa", "ieee", "mla")


def _initials(given: str) -> str:
    parts = [p for p in given.replace("-", " -").split() if p]
    return " ".join(f"{p[0]}." if not p.startswith("-") else f"-{p[1]}." for p in parts if p.strip("-"))


def _pages(r: Record, en_dash: bool = True) -> str:
    return r.pages.replace("-", "\u2013") if en_dash else r.pages  # en dash for page ranges


def _apa_names(people: list[Person]) -> str:
    names = [f"{p.family}, {_initials(p.given)}".rstrip(", ") for p in people]
    if not names:
        return ""
    if len(names) > 20:
        return ", ".join(names[:19]) + ", . . . " + names[-1]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + ", & " + names[-1]


def apa(r: Record) -> str:
    out = _apa_names(r.authors)
    out += f" ({r.year})." if r.year else " (n.d.)."
    if r.type in ("book", "monograph"):
        out += f" *{r.title}*."
        if r.publisher:
            out += f" {r.publisher}."
    else:
        out += f" {r.title}."
        if r.container:
            venue = f" *{r.container}*"
            if r.volume:
                venue += f", *{r.volume}*"
                if r.issue:
                    venue += f"({r.issue})"
            if r.pages:
                venue += f", {_pages(r)}"
            out += venue + "."
    if r.doi:
        out += f" https://doi.org/{r.doi}"
    return out.strip()


def ieee(r: Record) -> str:
    names = [f"{_initials(p.given)} {p.family}".strip() for p in r.authors]
    if len(names) > 6:
        who = f"{names[0]} et al."
    elif len(names) > 2:
        who = ", ".join(names[:-1]) + ", and " + names[-1]
    else:
        who = " and ".join(names)
    out = f'{who}, "{r.title},"' if who else f'"{r.title},"'
    if r.type in ("book", "monograph"):
        out = f"{who}, *{r.title}*." if who else f"*{r.title}*."
        if r.publisher:
            out += f" {r.publisher}"
        if r.year:
            out += f", {r.year}"
        out += "."
    else:
        prefix = " in " if "proceedings" in r.type or "proceedings" in r.container.lower() else " "
        parts = [f"{prefix.strip()} *{r.container}*".strip()] if r.container else []
        if r.volume:
            parts.append(f"vol. {r.volume}")
        if r.issue:
            parts.append(f"no. {r.issue}")
        if r.pages:
            parts.append(f"pp. {_pages(r)}")
        if r.year:
            parts.append(str(r.year))
        out += " " + ", ".join(parts) + "."
    if r.doi:
        out += f" doi: {r.doi}."
    return out.strip()


def mla(r: Record) -> str:
    a = r.authors
    if not a:
        who = ""
    elif len(a) == 1:
        who = f"{a[0].family}, {a[0].given}."
    elif len(a) == 2:
        who = f"{a[0].family}, {a[0].given}, and {a[1].given} {a[1].family}."
    else:
        who = f"{a[0].family}, {a[0].given}, et al."
    if r.type in ("book", "monograph"):
        out = f"{who} *{r.title}*."
        tail = [x for x in (r.publisher, str(r.year) if r.year else "") if x]
        if tail:
            out += " " + ", ".join(tail) + "."
    else:
        out = f'{who} "{r.title}."'
        parts = [f"*{r.container}*"] if r.container else []
        if r.volume:
            parts.append(f"vol. {r.volume}")
        if r.issue:
            parts.append(f"no. {r.issue}")
        if r.year:
            parts.append(str(r.year))
        if r.pages:
            parts.append(f"pp. {_pages(r)}")
        if parts:
            out += " " + ", ".join(parts) + "."
    if r.doi:
        out += f" https://doi.org/{r.doi}."
    return out.strip()


FORMATTERS: dict[str, Callable[[Record], str]] = {"apa": apa, "ieee": ieee, "mla": mla}


def format_record(r: Record, style: str) -> str:
    return FORMATTERS[style](r)


def plain(text: str) -> str:
    """Drop the *italic* markers for insertion into a document as plain text."""
    return text.replace("*", "")
