from __future__ import annotations

from app.domain.adm.outline import count_words
from app.domain.inspection.engine import check
from app.domain.inspection.model import Finding, InspectContext

PPTX = ("pptx",)
MAX_WORDS = 80
MIN_FONT_PT = 12


@check("SLIDE.MISSING_TITLE", formats=PPTX)
def missing_title(ctx: InspectContext) -> list[Finding]:
    return [
        Finding(
            code="SLIDE.MISSING_TITLE",
            category="slides",
            severity="medium",
            message=f"Slide {s.index + 1} has no title.",
            explanation="Titles drive navigation, accessibility and the outline view.",
            recommendation="Add a short title that states the slide's point.",
            node_ids=[s.id],
            page=s.index,
        )
        for s in ctx.adm.slides
        if not (s.title or "").strip() and not s.hidden
    ]


@check("SLIDE.TOO_MUCH_TEXT", formats=PPTX)
def too_much_text(ctx: InspectContext) -> list[Finding]:
    out = []
    for s in ctx.adm.slides:
        words = sum(count_words(sh.text) for sh in s.shapes)
        if words > MAX_WORDS:
            out.append(
                Finding(
                    code="SLIDE.TOO_MUCH_TEXT",
                    category="slides",
                    severity="medium",
                    message=f"Slide {s.index + 1} has {words} words.",
                    explanation=f"Slides with more than {MAX_WORDS} words are hard to read while listening.",
                    recommendation="Move detail to the speaker notes or split the slide.",
                    node_ids=[s.id],
                    page=s.index,
                    expected=MAX_WORDS,
                    actual=words,
                )
            )
    return out


@check("SLIDE.FONT_TOO_SMALL", formats=PPTX)
def font_too_small(ctx: InspectContext) -> list[Finding]:
    out = []
    for s in ctx.adm.slides:
        for sh in s.shapes:
            sizes = [r.fmt.size_pt for p in sh.paragraphs for r in p.runs if r.fmt.size_pt]
            if sizes and min(sizes) < MIN_FONT_PT:
                out.append(
                    Finding(
                        code="SLIDE.FONT_TOO_SMALL",
                        category="slides",
                        severity="medium",
                        message=f"Text in “{sh.name}” on slide {s.index + 1} is {min(sizes):g} pt.",
                        explanation=f"Text below {MIN_FONT_PT} pt cannot be read from the back of a room.",
                        recommendation=f"Use at least {MIN_FONT_PT} pt (18 pt or more for body text).",
                        node_ids=[sh.id],
                        page=s.index,
                        bbox=sh.bbox,
                        expected=MIN_FONT_PT,
                        actual=min(sizes),
                        fix_available=True,
                    )
                )
    return out


@check("SLIDE.OFF_SLIDE", formats=PPTX)
def off_slide(ctx: InspectContext) -> list[Finding]:
    if not ctx.adm.slide_size:
        return []
    w, h = ctx.adm.slide_size
    out = []
    for s in ctx.adm.slides:
        for sh in s.shapes:
            if sh.bbox is None:
                continue
            x0, y0, x1, y1 = sh.bbox
            if x0 < -1 or y0 < -1 or x1 > w + 1 or y1 > h + 1:
                out.append(
                    Finding(
                        code="SLIDE.OFF_SLIDE",
                        category="slides",
                        severity="high",
                        message=f"“{sh.name}” on slide {s.index + 1} extends beyond the slide edge.",
                        explanation="Content outside the slide area is cut off when presenting.",
                        recommendation="Move or resize the shape so it fits inside the slide.",
                        node_ids=[sh.id],
                        page=s.index,
                        bbox=(max(0, x0), max(0, y0), min(w, x1), min(h, y1)),
                        expected={"width": w, "height": h},
                        actual=sh.bbox,
                        fix_available=True,
                    )
                )
    return out


@check("SLIDE.NO_NOTES", formats=PPTX)
def no_notes(ctx: InspectContext) -> list[Finding]:
    missing = [s.index + 1 for s in ctx.adm.slides if not s.notes.strip() and s.index > 0]
    if not missing or len(ctx.adm.slides) < 3:
        return []
    return [
        Finding(
            code="SLIDE.NO_NOTES",
            category="slides",
            severity="info",
            message=f"{len(missing)} slide(s) have no speaker notes: {', '.join(map(str, missing[:12]))}.",
            explanation="Speaker notes help presenters and make the deck usable on its own.",
            recommendation="Add short speaker notes to each content slide.",
        )
    ]
