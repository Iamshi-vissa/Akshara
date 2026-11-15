"""PPTX → ADM importer (python-pptx).

Text inherited from slide layouts/masters (e.g. placeholder font sizes) is not always present
on the shape itself; such values stay ``None`` (unknown) rather than being guessed. Overflow
is judged later from the rendered slides (visual engine), not from metadata.
"""

from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER
from pptx.enum.text import MSO_AUTO_SIZE, PP_ALIGN
from pptx.util import Emu

from app.domain.adm.model import (
    AdmDocument,
    Metadata,
    ParaFmt,
    Paragraph,
    Run,
    RunFmt,
    Shape,
    Slide,
    Source,
)
from app.domain.adm.outline import count_words

ALIGN = {
    PP_ALIGN.LEFT: "left",
    PP_ALIGN.CENTER: "center",
    PP_ALIGN.RIGHT: "right",
    PP_ALIGN.JUSTIFY: "justify",
}
AUTOFIT = {
    MSO_AUTO_SIZE.NONE: "none",
    MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE: "normal",
    MSO_AUTO_SIZE.SHAPE_TO_FIT_TEXT: "shape",
}


def _pt(v: int | None) -> float | None:
    return round(Emu(v).pt, 1) if v is not None else None


def _placeholder(shape) -> str | None:  # type: ignore[no-untyped-def]
    if not shape.is_placeholder:
        return None
    t = shape.placeholder_format.type
    if t in (PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE, PP_PLACEHOLDER.VERTICAL_TITLE):
        return "title"
    if t == PP_PLACEHOLDER.SUBTITLE:
        return "subtitle"
    return "body"


def import_pptx(path: Path) -> AdmDocument:
    prs = Presentation(str(path))
    sw, sh = _pt(prs.slide_width) or 720.0, _pt(prs.slide_height) or 540.0
    slides: list[Slide] = []
    words = 0
    for si, slide in enumerate(prs.slides):
        shapes: list[Shape] = []
        title = None
        for shp in slide.shapes:
            bbox = None
            if shp.left is not None and shp.top is not None and shp.width is not None and shp.height is not None:
                bbox = (
                    _pt(shp.left),
                    _pt(shp.top),
                    _pt(shp.left + shp.width),
                    _pt(shp.top + shp.height),
                )
            ph = _placeholder(shp)
            kind = "other"
            paragraphs: list[Paragraph] = []
            autofit = "unknown"
            if shp.has_text_frame:
                kind = "text"
                tf = shp.text_frame
                autofit = AUTOFIT.get(tf.auto_size, "unknown") if tf.auto_size is not None else "unknown"
                for pi, para in enumerate(tf.paragraphs):
                    runs = [
                        Run(
                            text=r.text,
                            fmt=RunFmt(
                                font_family=r.font.name,
                                size_pt=r.font.size.pt if r.font.size else None,
                                bold=r.font.bold,
                                italic=r.font.italic,
                            ),
                        )
                        for r in para.runs
                        if r.text
                    ]
                    if not runs:
                        continue
                    paragraphs.append(
                        Paragraph(
                            id=f"s{si}.sh{shp.shape_id}.p{pi}",
                            source=Source(fmt="pptx", slide=si, shape_id=shp.shape_id, index=pi),
                            runs=runs,
                            fmt=ParaFmt(alignment=ALIGN.get(para.alignment)),
                            role="list_item" if para.level > 0 else "body",
                            list_level=para.level or None,
                        )
                    )
                    words += count_words(para.text)
                if ph == "title" and paragraphs:
                    title = " ".join(p.text for p in paragraphs)
            elif shp.shape_type == MSO_SHAPE_TYPE.PICTURE:
                kind = "picture"
            elif shp.has_table:
                kind = "table"
            shapes.append(
                Shape(
                    id=f"s{si}.sh{shp.shape_id}",
                    kind=kind,
                    name=shp.name,
                    placeholder=ph,
                    bbox=bbox,
                    paragraphs=paragraphs,
                    autofit=autofit,
                )
            )
        notes = (
            slide.notes_slide.notes_text_frame.text
            if slide.has_notes_slide and slide.notes_slide.notes_text_frame
            else ""
        )
        slides.append(
            Slide(
                id=f"s{si}",
                index=si,
                layout=slide.slide_layout.name,
                title=title,
                shapes=shapes,
                notes=notes,
                hidden=slide._element.get("show") == "0",
            )
        )
    cp = prs.core_properties
    meta = Metadata(
        title=cp.title or None,
        authors=[cp.author] if cp.author else [],
        subject=cp.subject or None,
        page_count=len(slides),
        word_count=words,
    )
    return AdmDocument(source_format="pptx", metadata=meta, slides=slides, slide_size=(sw, sh))
