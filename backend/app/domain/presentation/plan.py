"""Build a slide plan and fit text to slide budgets.

Fitting is deterministic: each layout has a character/line budget derived from the text box
size and font size. Too much content is never squeezed below the minimum readable size; it
is split onto a continuation slide instead. Rendering-based overflow checks (visual engine)
then confirm the result.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Literal

from app.domain.adm.model import AdmDocument, Heading, Paragraph
from app.domain.adm.outline import section_role

Layout = Literal["title", "section", "bullets", "two_column", "closing"]
MIN_BODY_PT = 18.0
MAX_BULLETS = 6
MAX_BULLET_WORDS = 18


@dataclass
class SlideSpec:
    layout: Layout
    title: str
    bullets: list[str] = field(default_factory=list)
    right: list[str] = field(default_factory=list)  # two_column right side
    subtitle: str = ""
    notes: str = ""
    font_pt: float = 24.0


@dataclass
class Box:
    width_pt: float
    height_pt: float


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(])", " ".join(text.split())) if s.strip()]


def _shorten(sentence: str, max_words: int = MAX_BULLET_WORDS) -> str:
    words = sentence.rstrip(".").split()
    if len(words) <= max_words:
        return " ".join(words)
    cut = words[:max_words]
    # Prefer ending at a natural break (comma/semicolon) within the budget.
    for i in range(len(cut) - 1, max_words // 2, -1):
        if cut[i].endswith((",", ";", ":")):
            return " ".join(cut[: i + 1]).rstrip(",;:") + "…"
    return " ".join(cut) + "…"


def lines_needed(text: str, width_pt: float, font_pt: float) -> int:
    chars_per_line = max(8, int(width_pt / (font_pt * 0.52)))
    return max(1, math.ceil(len(text) / chars_per_line))


def fits(bullets: list[str], box: Box, font_pt: float) -> bool:
    line_h = font_pt * 1.25
    total = sum(lines_needed(b, box.width_pt - 24, font_pt) for b in bullets) * line_h + len(bullets) * font_pt * 0.35
    return total <= box.height_pt


def fit_slides(slides: list[SlideSpec], box: Box, two_col_box: Box) -> list[SlideSpec]:
    """Choose the largest font that fits (down to MIN_BODY_PT); split slides that still overflow."""
    out: list[SlideSpec] = []
    for s in slides:
        if s.layout not in ("bullets", "two_column"):
            out.append(s)
            continue
        b = two_col_box if s.layout == "two_column" else box
        pending = list(s.bullets)
        part = 0
        while True:
            chunk: list[str] = []
            for item in pending:
                if len(chunk) < MAX_BULLETS and fits([*chunk, item], b, MIN_BODY_PT):
                    chunk.append(item)
                else:
                    break
            if not chunk and pending:  # a single bullet longer than a whole slide
                chunk = [_shorten(pending[0], 40)]
                pending = pending[1:]
            else:
                pending = pending[len(chunk) :]
            font = next(
                (
                    f
                    for f in (28.0, 24.0, 22.0, 20.0, MIN_BODY_PT)
                    if fits(chunk, b, f) and (s.layout != "two_column" or fits(s.right, two_col_box, f))
                ),
                MIN_BODY_PT,
            )
            title = s.title if part == 0 else f"{s.title} (cont.)"
            out.append(
                SlideSpec(
                    layout=s.layout,
                    title=title,
                    bullets=chunk,
                    right=s.right if part == 0 else [],
                    notes=s.notes,
                    font_pt=font,
                )
            )
            part += 1
            if not pending:
                break
    return out


def from_document(adm: AdmDocument, max_slides: int = 20) -> list[SlideSpec]:
    """Deterministic deck from a document: title, agenda, one slide per section, references, closing."""
    title = adm.metadata.title or next((h.text for h in adm.headings() if h.level == 0), "") or "Presentation"
    heads = [h for h in adm.headings() if h.level >= 1]
    top = [h for h in heads if h.level == min((x.level for x in heads), default=1)]
    slides = [SlideSpec("title", title, subtitle=", ".join(adm.metadata.authors))]
    agenda = [h.text for h in top if section_role(h.text) not in ("references", "abstract", "acknowledgements")]
    if len(agenda) >= 3:
        slides.append(
            SlideSpec(
                "bullets",
                "Agenda",
                bullets=[re.sub(r"^\s*[\dIVXLC]+(\.\d+)*\.?\s+", "", a) for a in agenda[:8]],
                notes=f"Outline of the talk: {len(agenda)} parts.",
            )
        )
    body = adm.body
    refs: list[str] = []
    for h in heads:
        content: list[Paragraph] = []
        for b in body[body.index(h) + 1 :]:
            if isinstance(b, Heading):
                break
            if isinstance(b, Paragraph) and b.role not in ("empty",):
                content.append(b)
        role = section_role(h.text)
        clean_title = re.sub(r"^\s*[\dIVXLC]+(\.\d+)*\.?\s+", "", h.text.strip())
        if role == "references":
            refs = [p.text.strip() for p in content if p.text.strip()]
            continue
        bullets = [
            _shorten(_sentences(p.text)[0]) for p in content if p.role != "reference_entry" and _sentences(p.text)
        ]
        if not bullets:
            continue
        notes = " ".join(" ".join(_sentences(p.text)[:2]) for p in content)[:1500]
        slides.append(SlideSpec("bullets", clean_title, bullets=bullets, notes=notes))
        if len(slides) >= max_slides - 2:
            break
    if refs:
        slides.append(
            SlideSpec(
                "bullets",
                "References",
                bullets=[_shorten(r, 24) for r in refs[:8]],
                notes="Full references are in the source document.",
            )
        )
    slides.append(SlideSpec("closing", "Questions?", subtitle=title, notes="Thank the audience and invite questions."))
    return slides


def from_outline_text(text: str) -> list[SlideSpec]:
    """Parse a simple outline: '# Title' starts a slide, '- item' adds a bullet, '> note' adds notes,
    '## Section' makes a section divider. The first slide becomes the title slide."""
    slides: list[SlideSpec] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("## "):
            slides.append(SlideSpec("section", line[3:].strip()))
        elif line.startswith("# "):
            slides.append(SlideSpec("bullets", line[2:].strip()))
        elif re.match(r"^\s*[-*•]\s+", line) and slides:
            slides[-1].bullets.append(re.sub(r"^\s*[-*•]\s+", "", line).strip())
        elif line.startswith(">") and slides:
            slides[-1].notes = (slides[-1].notes + " " + line[1:].strip()).strip()
        elif slides:
            slides[-1].bullets.append(line.strip())
    if slides and not slides[0].bullets:
        slides[0] = SlideSpec("title", slides[0].title, notes=slides[0].notes)
    return slides
