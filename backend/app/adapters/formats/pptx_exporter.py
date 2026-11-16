"""Slide plan → PPTX with a consistent theme, slide numbers and speaker notes (python-pptx).

Themes are defined here as data (colours + fonts) and applied to every shape, so a deck is
visually consistent regardless of the default template.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Emu, Pt

from app.domain.presentation.plan import Box, SlideSpec


@dataclass(frozen=True)
class Theme:
    key: str
    label: str
    background: str
    title: str
    text: str
    accent: str
    muted: str
    heading_font: str
    body_font: str


THEMES: dict[str, Theme] = {
    "paper": Theme(
        "paper", "Paper (light, classic)", "FFFFFF", "1F2937", "374151", "4F46E5", "6B7280", "Georgia", "Calibri"
    ),
    "ink": Theme(
        "ink", "Ink (dark, high contrast)", "0B0D14", "ECEDF4", "C7CADA", "8B93FF", "8A90A8", "Georgia", "Calibri"
    ),
    "academic": Theme(
        "academic", "Academic (navy on white)", "FFFFFF", "0F2B5B", "1F2937", "B45309", "64748B", "Cambria", "Calibri"
    ),
    "corporate": Theme(
        "corporate", "Corporate (teal accents)", "F8FAFC", "0F172A", "334155", "0D9488", "64748B", "Calibri", "Calibri"
    ),
}

W, H = 13.333 * 72, 7.5 * 72  # 16:9 in points
MARGIN = 54.0
BODY_BOX = Box(width_pt=W - 2 * MARGIN, height_pt=H - 170 - 70)
TWO_COL_BOX = Box(width_pt=(W - 2 * MARGIN - 36) / 2, height_pt=H - 170 - 70)


def _rgb(hex_: str) -> RGBColor:
    return RGBColor(int(hex_[0:2], 16), int(hex_[2:4], 16), int(hex_[4:6], 16))  # type: ignore[no-untyped-call]


def _text(  # type: ignore[no-untyped-def]
    shape,
    text: str,
    *,
    size: float,
    color: str,
    font: str,
    bold: bool = False,
    align: PP_ALIGN = PP_ALIGN.LEFT,
) -> None:
    tf = shape.text_frame
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.text = text
    for p in tf.paragraphs:
        p.alignment = align
        for r in p.runs:
            r.font.size, r.font.bold, r.font.name = Pt(size), bold, font
            r.font.color.rgb = _rgb(color)


def _place(shape, x: float, y: float, w: float, h: float):  # type: ignore[no-untyped-def]
    shape.left, shape.top, shape.width, shape.height = Pt(x), Pt(y), Pt(w), Pt(h)
    return shape


def _slide_number(slide, theme: Theme, n: int) -> None:  # type: ignore[no-untyped-def]
    box = slide.shapes.add_textbox(Pt(W - MARGIN - 60), Pt(H - 40), Pt(60), Pt(24))
    p = box.text_frame.paragraphs[0]
    p.alignment = PP_ALIGN.RIGHT
    # <a:fld type="slidenum"> — a real field, so numbers stay correct if slides are reordered.
    fld = OxmlElement("a:fld")
    fld.set("id", "{B6F15528-21DE-4FAA-801E-634DDDAF4B2B}")
    fld.set("type", "slidenum")
    rpr = OxmlElement("a:rPr")
    rpr.set("lang", "en-US")
    rpr.set("sz", "1200")
    fill = OxmlElement("a:solidFill")
    clr = OxmlElement("a:srgbClr")
    clr.set("val", theme.muted)
    fill.append(clr)
    rpr.append(fill)
    fld.append(rpr)
    t = OxmlElement("a:t")
    t.text = str(n)  # cached value for viewers that do not evaluate fields
    fld.append(t)
    p_el = p._p
    end = p_el.find(qn("a:endParaRPr"))
    if end is not None:
        end.addprevious(fld)
    else:
        p_el.append(fld)


def export_pptx(slides: list[SlideSpec], theme_key: str = "paper", title: str = "", author: str = "") -> bytes:
    theme = THEMES.get(theme_key, THEMES["paper"])
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(int(W * 12700)), Emu(int(H * 12700))
    # "Title Only": every slide gets a real title placeholder (screen readers, outline view, and
    # our own SLIDE.MISSING_TITLE check rely on it); everything else is positioned explicitly.
    title_only = prs.slide_layouts[5]
    for n, spec in enumerate(slides, start=1):
        slide = prs.slides.add_slide(title_only)
        bg = slide.background.fill
        bg.solid()
        bg.fore_color.rgb = _rgb(theme.background)
        if spec.layout in ("title", "closing", "section"):
            band = slide.shapes.add_shape(1, Pt(MARGIN), Pt(H / 2 + 46), Pt(120), Pt(5))
            band.fill.solid()
            band.fill.fore_color.rgb = _rgb(theme.accent)
            band.line.fill.background()
            t = _place(slide.shapes.title, MARGIN, H / 2 - 110, W - 2 * MARGIN, 150)
            t.text_frame.vertical_anchor = MSO_ANCHOR.BOTTOM
            size = 44 if spec.layout != "section" else 40
            _text(t, spec.title, size=size, color=theme.title, font=theme.heading_font, bold=True)
            if spec.subtitle:
                s = slide.shapes.add_textbox(Pt(MARGIN), Pt(H / 2 + 64), Pt(W - 2 * MARGIN), Pt(60))
                s.name = "Subtitle"
                _text(s, spec.subtitle, size=22, color=theme.muted, font=theme.body_font)
        else:
            t = _place(slide.shapes.title, MARGIN, 40, W - 2 * MARGIN, 80)
            t.text_frame.vertical_anchor = MSO_ANCHOR.BOTTOM
            _text(t, spec.title, size=34, color=theme.title, font=theme.heading_font, bold=True)
            rule = slide.shapes.add_shape(1, Pt(MARGIN), Pt(128), Pt(64), Pt(4))
            rule.fill.solid()
            rule.fill.fore_color.rgb = _rgb(theme.accent)
            rule.line.fill.background()
            cols = (
                [(spec.bullets, MARGIN, BODY_BOX)]
                if spec.layout == "bullets"
                else [
                    (spec.bullets, MARGIN, TWO_COL_BOX),
                    (spec.right, MARGIN + TWO_COL_BOX.width_pt + 36, TWO_COL_BOX),
                ]
            )
            for items, x, box in cols:
                body = slide.shapes.add_textbox(Pt(x), Pt(150), Pt(box.width_pt), Pt(box.height_pt))
                body.name = "Body"
                tf = body.text_frame
                tf.word_wrap, tf.auto_size = True, MSO_AUTO_SIZE.NONE
                for i, item in enumerate(items):
                    p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                    p.space_after = Pt(spec.font_pt * 0.35)
                    bullet = p.add_run()
                    bullet.text = "▪  "
                    bullet.font.color.rgb, bullet.font.size, bullet.font.name = (
                        _rgb(theme.accent),
                        Pt(spec.font_pt),
                        theme.body_font,
                    )
                    r = p.add_run()
                    r.text = item
                    r.font.size, r.font.name = Pt(spec.font_pt), theme.body_font
                    r.font.color.rgb = _rgb(theme.text)
        if n > 1:
            _slide_number(slide, theme, n)
        if spec.notes:
            slide.notes_slide.notes_text_frame.text = spec.notes
    cp = prs.core_properties
    cp.title = title or (slides[0].title if slides else "")
    if author:
        cp.author = author
    cp.comments = "Created in AKSHARA."
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()
