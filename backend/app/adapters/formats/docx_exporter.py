"""ADM → new DOCX (for generated documents). Existing documents are patched instead (D6).

Real Word styles are used (Normal, Title, Heading 1-3, Caption), so the result has a proper
outline, navigation pane and table-of-contents support, and AKSHARA's own importer reads the
same structure back.
"""

from __future__ import annotations

import io

from docx import Document
from docx.enum.section import WD_ORIENT, WD_SECTION_START
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

from app.domain.adm.model import AdmDocument, Caption, Heading, PageBreak, Paragraph, Table
from app.domain.generation.style import StyleSpec

from .docx_patcher import PAPER_PT, _page_field_paragraph, _set_fonts

ALIGN = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
}


def _style_font(style, font: str, size: float | None, bold: bool | None = None) -> None:  # type: ignore[no-untyped-def]
    style.font.name = font
    _set_fonts(style.element.get_or_add_rPr(), font)
    if size:
        style.font.size = Pt(size)
    if bold is not None:
        style.font.bold = bold
    style.font.color.rgb = None


def export_docx(adm: AdmDocument, spec: StyleSpec) -> bytes:
    doc = Document()
    sec = doc.sections[0]
    w, h = PAPER_PT.get(spec.paper, PAPER_PT["Letter"])
    sec.orientation = WD_ORIENT.PORTRAIT
    sec.page_width, sec.page_height = Pt(w), Pt(h)
    sec.top_margin, sec.bottom_margin, sec.left_margin, sec.right_margin = (Pt(v) for v in spec.margins_pt)

    normal = doc.styles["Normal"]
    _style_font(normal, spec.font, spec.size_pt)
    normal.paragraph_format.line_spacing = spec.line_spacing
    normal.paragraph_format.space_after = Pt(0 if spec.line_spacing >= 2 else 6)
    normal.paragraph_format.alignment = ALIGN.get(spec.alignment, WD_ALIGN_PARAGRAPH.LEFT)
    for lvl, size in ((1, spec.size_pt + 2), (2, spec.size_pt + 1), (3, spec.size_pt)):
        hs = doc.styles[f"Heading {lvl}"]
        _style_font(hs, spec.font, size, bold=True)
        hs.paragraph_format.line_spacing = spec.line_spacing
        hs.paragraph_format.space_before = Pt(12)
        hs.paragraph_format.space_after = Pt(6)
    _style_font(doc.styles["Title"], spec.font, spec.size_pt + 8, bold=True)
    _style_font(doc.styles["Caption"], spec.font, spec.size_pt, bold=False)
    doc.styles["Caption"].font.italic = False

    two_cols_started = False
    for b in adm.body:
        if isinstance(b, Heading):
            if b.level == 0:
                doc.add_paragraph(b.text, style="Title")
                continue
            if spec.columns > 1 and not two_cols_started:
                new = doc.add_section(WD_SECTION_START.CONTINUOUS)  # columns start after the title
                cols = new._sectPr.find(qn("w:cols"))
                if cols is None:
                    cols = OxmlElement("w:cols")
                    new._sectPr.append(cols)
                cols.set(qn("w:num"), str(spec.columns))
                cols.set(qn("w:space"), str(int(0.25 * 1440)))
                two_cols_started = True
            doc.add_heading(b.text, level=min(b.level, 3))
        elif isinstance(b, Caption):
            doc.add_paragraph(b.text, style="Caption")
        elif isinstance(b, Paragraph):
            if b.role == "empty":
                continue
            p = doc.add_paragraph(b.text)
            if b.role == "reference_entry":
                p.paragraph_format.left_indent = Pt(36)
                p.paragraph_format.first_line_indent = Pt(-36)
            elif b.role == "list_item":
                p.style = doc.styles["List Bullet"]
        elif isinstance(b, Table) and b.rows:
            cols = max(len(r) for r in b.rows)
            t = doc.add_table(rows=len(b.rows), cols=cols)
            t.style = doc.styles["Table Grid"]
            for i, row in enumerate(b.rows):
                for j, cell in enumerate(row):
                    t.cell(i, j).text = cell.text
        elif isinstance(b, PageBreak):
            doc.add_page_break()  # type: ignore[no-untyped-call]

    for s in doc.sections:
        part = s.header if spec.page_numbers.startswith("header") else s.footer
        par = part.paragraphs[0]
        par.alignment = WD_ALIGN_PARAGRAPH.RIGHT if spec.page_numbers.endswith("right") else WD_ALIGN_PARAGRAPH.CENTER
        _page_field_paragraph(par)

    cp = doc.core_properties
    cp.title = adm.metadata.title or ""
    cp.author = ", ".join(adm.metadata.authors)
    cp.keywords = ", ".join(adm.metadata.keywords)
    cp.comments = "Drafted in AKSHARA. Generated passages must be reviewed; only user-supplied references are cited."
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()
