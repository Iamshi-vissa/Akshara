from __future__ import annotations

import io

from pptx import Presentation

from app.adapters.formats.pptx_exporter import BODY_BOX, THEMES, TWO_COL_BOX, export_pptx
from app.domain.presentation.plan import MAX_BULLETS, MIN_BODY_PT, SlideSpec, fit_slides, from_outline_text


def test_outline_parsing() -> None:
    slides = from_outline_text("# Deck\n> hello\n## Part one\n# Slide\n- a\n* b\nplain line\n> note")
    assert [s.layout for s in slides] == ["title", "section", "bullets"]
    assert slides[0].notes == "hello" and slides[2].bullets == ["a", "b", "plain line"] and slides[2].notes == "note"


def test_fitting_splits_overflow_and_respects_minimum_font() -> None:
    long = "A deliberately long bullet point that wraps across the line several times to use space " * 2
    slides = fit_slides([SlideSpec("bullets", "Many", bullets=[long] * 14)], BODY_BOX, TWO_COL_BOX)
    assert len(slides) >= 3 and slides[1].title == "Many (cont.)"
    assert all(len(s.bullets) <= MAX_BULLETS and s.font_pt >= MIN_BODY_PT for s in slides)
    assert sum(len(s.bullets) for s in slides) == 14  # nothing dropped


def test_short_slides_get_large_type() -> None:
    (s,) = fit_slides([SlideSpec("bullets", "Few", bullets=["One", "Two"])], BODY_BOX, TWO_COL_BOX)
    assert s.font_pt == 28.0


def test_export_has_titles_numbers_notes_and_theme() -> None:
    slides = [
        SlideSpec("title", "Deck", subtitle="Me"),
        SlideSpec("bullets", "Body", bullets=["x"], notes="say x", font_pt=24),
        SlideSpec("closing", "End", notes="bye"),
    ]
    prs = Presentation(io.BytesIO(export_pptx(slides, "ink", author="Me")))
    assert prs.core_properties.title == "Deck" and prs.core_properties.author == "Me"
    assert [s.shapes.title.text for s in prs.slides] == ["Deck", "Body", "End"]
    assert prs.slides[1].notes_slide.notes_text_frame.text == "say x"
    xml = [s._element.xml for s in prs.slides]
    assert 'type="slidenum"' not in xml[0] and all('type="slidenum"' in x for x in xml[1:])
    bg = prs.slides[0].background.fill.fore_color.rgb
    assert str(bg) == THEMES["ink"].background
