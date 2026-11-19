"""Read a reference-list entry as written: label, authors, year, title, DOI, URLs.

Heuristic and style-agnostic (IEEE, APA, MLA, Harvard and close variants). It never invents
fields: anything it cannot find stays empty, and verification then relies on what is present.
"""

from __future__ import annotations

import re
import unicodedata

from app.domain.references.model import Parsed

DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)", re.I)
URL_RE = re.compile(r"\bhttps?://[^\s<>\"]+", re.I)
LABEL_RE = re.compile(r"^\s*(\[\d{1,4}\]|\d{1,4}\.(?=\s))\s*")
YEAR_RE = re.compile(r"(?<!\d)(1[89]\d\d|20\d\d)(?!\d)")
QUOTED_RE = re.compile(r"[\"“”]([^\"“”]{6,400}?)[,.]?[\"“”]")
NAME_TOKEN = re.compile(r"[A-ZÀ-ÖØ-Þ][\w'\u2019\-]+")
IEEE_NAME = re.compile(r"^(?:and\s+)?(?:[A-Z]\.\s*-?\s*)+[A-ZÀ-ÖØ-Þ][\w'\u2019\-]+$")
STOP = {"and", "et", "al", "in", "the", "eds", "ed", "pp", "vol", "no"}


def clean_doi(doi: str) -> str:
    doi = doi.strip().rstrip(".,;)]}>")
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", doi, flags=re.I)
    return doi.lower()


def _strip_urls(text: str) -> str:
    text = URL_RE.sub(" ", text)
    text = re.sub(r"\bdoi:\s*\S+", " ", text, flags=re.I)
    return DOI_RE.sub(" ", text)


def _authors(segment: str) -> list[str]:
    """Family names from an author segment ("A. Author, B. Writer and C. D. Third")."""
    segment = re.sub(r"\bet al\.?", "", segment)
    parts = re.split(r",|;|\band\b|&", segment)
    out: list[str] = []
    pending_family: str | None = None
    for part in (p.strip() for p in parts):
        if not part:
            continue
        tokens = [t for t in NAME_TOKEN.findall(part) if t.lower() not in STOP]
        initials_only = re.fullmatch(r"(?:[A-Z]\.\s*-?)+", part) is not None
        if initials_only and pending_family:  # APA "Author, A. B." — family came first
            out.append(pending_family)
            pending_family = None
            continue
        if pending_family and not out and len(tokens) == 1 and "." not in part:
            out.append(pending_family)  # MLA "Family, Given" — this part is the given name
            pending_family = None
            continue
        if pending_family:
            out.append(pending_family)
            pending_family = None
        if not tokens:
            continue
        if re.match(r"^(?:[A-Z]\.\s*-?)+\s*[A-Z]", part):  # IEEE "A. B. Family"
            out.append(tokens[-1])
        elif len(tokens) == 1:
            pending_family = tokens[0]  # wait: next part may be its initials
        else:  # "Given Family" (MLA second author) or "Family Given"
            out.append(tokens[-1])
    if pending_family:
        out.append(pending_family)
    return out[:30]


def parse_reference(text: str) -> Parsed:
    raw = " ".join(text.split())
    p = Parsed(raw=raw)
    m = LABEL_RE.match(raw)
    rest = raw
    if m:
        p.label = m.group(1)
        rest = raw[m.end() :]
    dois = DOI_RE.findall(raw)
    if dois:
        p.doi = clean_doi(dois[0])
    p.urls = [u.rstrip(".,;)") for u in URL_RE.findall(raw) if "doi.org/" not in u.lower()][:3]
    body = _strip_urls(rest)
    years = [int(y) for y in YEAR_RE.findall(body)]
    p.year = years[0] if years else None

    q = QUOTED_RE.search(body)
    if q:  # IEEE / MLA: authors, "Title," venue
        p.title = q.group(1).strip()
        p.authors = _authors(body[: q.start()])
        return p
    ym = re.search(r"\((1[89]\d\d|20\d\d)[a-z]?(?:,[^)]*)?\)\.?", body)
    if ym:  # APA / Harvard: Authors (Year). Title. Venue
        p.authors = _authors(body[: ym.start()])
        after = body[ym.end() :].strip()
        p.title = re.split(r"(?<=[a-z0-9)\]])[.?!]\s", after, maxsplit=1)[0].strip().rstrip(".")
        return p
    # Fallback: "Authors. Title. Venue, year." — first sentence is authors, second the title.
    sentences = [s.strip() for s in re.split(r"(?<=[a-z0-9)])\.\s+", body) if s.strip()]
    if sentences:  # IEEE book: "A. Author and B. Writer, Title. City: Publisher, year."
        segs = [x.strip() for x in sentences[0].split(",")]
        n = 0
        while n < len(segs) and all(IEEE_NAME.match(x) for x in re.split(r"\s+and\s+", segs[n]) if x):
            n += 1
        if 0 < n < len(segs):
            p.authors = _authors(", ".join(segs[:n]))
            p.title = ", ".join(segs[n:]).strip().rstrip(".")
            return p
    if len(sentences) >= 2:
        p.authors = _authors(sentences[0])
        p.title = sentences[1].rstrip(".")
    return p


def normalise_title(t: str) -> str:
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    t = re.sub(r"<[^>]+>", " ", t)
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t.lower()).split())
