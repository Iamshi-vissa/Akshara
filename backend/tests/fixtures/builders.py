"""Programmatic test documents with *known* properties (ARCHITECTURE.md §2).

Every defect in ``defective_report.docx`` is deliberate and listed in ``KNOWN_DEFECTS``; the
inspection and UDSE tests assert that exactly these are found. ``clean_report.docx`` follows
one consistent house style (Letter, 1-inch margins, Times New Roman 12 pt, double spacing) and
must produce no findings above ``low``.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pymupdf
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt
from pptx import Presentation
from pptx.util import Inches as PInches
from pptx.util import Pt as PPt

KNOWN_DEFECTS = {
    "STRUCT.HEADING_LEVEL_SKIP",
    "STRUCT.HEADING_NUMBERING",
    "STRUCT.MISSING_SECTION",  # no abstract
    "FMT.HEADING_INCONSISTENT",
    "FMT.FONT_INCONSISTENT",
    "FMT.SPACING_INCONSISTENT",
    "FIG.MISSING_CAPTION",
    "FIG.NUMBERING",
    "TBL.NOT_REFERENCED",
    "LAYOUT.EMPTY_PARAGRAPHS",
    "PAGE.NO_PAGE_NUMBERS",
    "PAGE.MARGINS_INCONSISTENT",
}


def png_bytes(w: int = 240, h: int = 160) -> bytes:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, w, h), False)
    pix.clear_with(200)
    return pix.tobytes("png")


def _base_style(
    doc: Document, font: str = "Times New Roman", size: int = 12, spacing: float = 2.0
) -> None:
    st = doc.styles["Normal"]
    st.font.name = font
    st.font.size = Pt(size)
    st.element.rPr.rFonts.set(qn("w:ascii"), font)
    st.paragraph_format.line_spacing = spacing
    st.paragraph_format.space_after = Pt(0)
    for lvl in (1, 2, 3):
        hs = doc.styles[f"Heading {lvl}"]
        hs.font.name = font
        hs.element.rPr.rFonts.set(qn("w:ascii"), font)
        hs.font.size = Pt(size)
        hs.font.bold = True
        hs.font.color.rgb = None
        hs.paragraph_format.space_before = Pt(12)
        hs.paragraph_format.space_after = Pt(6)
        hs.paragraph_format.line_spacing = spacing
    cap = doc.styles["Caption"]
    cap.font.name = font
    cap.font.size = Pt(size)
    cap.font.color.rgb = None
    cap.font.italic = False
    cap.paragraph_format.line_spacing = spacing


def _page_number_footer(section) -> None:  # type: ignore[no-untyped-def]
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    for kind, text in (("begin", None), (None, "PAGE"), ("end", None)):
        if kind:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), kind)
        else:
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = text
        run._r.append(el)


def _margins(section, inches: float, left: float | None = None) -> None:  # type: ignore[no-untyped-def]
    section.page_width, section.page_height = Inches(8.5), Inches(11)
    section.top_margin = section.bottom_margin = section.right_margin = Inches(inches)
    section.left_margin = Inches(left if left is not None else inches)


def _image(doc: Document, tmp: Path) -> None:
    img = tmp / "fig.png"
    img.write_bytes(png_bytes())
    doc.add_picture(str(img), width=Inches(3))


BODY = (
    "Document engineering treats a report as a structured artefact whose quality can be measured. "
    "This paragraph provides enough text to behave like real body content in tests."
)


def build_clean_report(path: Path) -> Path:
    doc = Document()
    _base_style(doc)
    sec = doc.sections[0]
    _margins(sec, 1.0)
    _page_number_footer(sec)
    doc.core_properties.title = "Quality Assurance for Technical Documents"
    doc.core_properties.author = "A. Researcher"
    doc.add_heading(
        "Quality Assurance for Technical Documents", level=0
    ).style.font.name = "Times New Roman"
    doc.add_heading("Abstract", level=1)
    doc.add_paragraph("This report studies automated checks for document structure and formatting.")
    doc.add_heading("1. Introduction", level=1)
    doc.add_paragraph(BODY + " As shown in Figure 1, the pipeline has three stages.")
    with tempfile.TemporaryDirectory() as t:
        _image(doc, Path(t))
    doc.add_paragraph("Figure 1. Overview of the processing pipeline.", style="Caption")
    doc.add_heading("2. Methodology", level=1)
    doc.add_heading("2.1 Data Collection", level=2)
    doc.add_paragraph(BODY + " Table 1 lists the corpus.")
    doc.add_paragraph("Table 1. Corpus statistics.", style="Caption")
    table = doc.add_table(rows=2, cols=2)
    for r, row in enumerate([("Documents", "120"), ("Pages", "2,400")]):
        for c, val in enumerate(row):
            table.cell(r, c).text = val
    doc.add_heading("2.2 Analysis", level=2)
    doc.add_paragraph(BODY)
    doc.add_heading("3. Results", level=1)
    doc.add_paragraph(BODY)
    doc.add_heading("4. Conclusion", level=1)
    doc.add_paragraph(BODY)
    doc.add_heading("References", level=1)
    doc.add_paragraph(
        '[1] A. Author, "A study of documents," Journal of Testing, vol. 1, no. 2, pp. 1-10, 2020.'
    )
    doc.add_paragraph("[2] B. Writer, Structured Writing. New York, NY, USA: Example Press, 2019.")
    doc.save(str(path))
    return path


def build_defective_report(path: Path) -> Path:
    doc = Document()
    _base_style(doc)
    sec = doc.sections[0]
    _margins(sec, 1.0, left=0.5)  # PAGE.MARGINS_INCONSISTENT (vs second section)
    # PAGE.NO_PAGE_NUMBERS: no footer field.
    doc.add_heading("Untitled Project Report", level=0)
    # STRUCT.MISSING_SECTION: no Abstract.
    doc.add_heading("1. Introduction", level=1)
    doc.add_paragraph(BODY + " Figure 1 and Figure 3 show results.")
    doc.add_heading("1.1.1 Deep Detail", level=3)  # STRUCT.HEADING_LEVEL_SKIP (1 -> 3)
    doc.add_paragraph(BODY)
    h = doc.add_heading("2. Methods", level=1)
    for r in h.runs:  # FMT.HEADING_INCONSISTENT: one H1 in Arial 16
        r.font.name = "Arial"
        r.font.size = Pt(16)
    p = doc.add_paragraph(BODY)  # FMT.FONT_INCONSISTENT: one body paragraph in Arial 10
    for r in p.runs:
        r.font.name = "Arial"
        r.font.size = Pt(10)
    p2 = doc.add_paragraph(BODY)  # FMT.SPACING_INCONSISTENT: single spacing in a double-spaced doc
    p2.paragraph_format.line_spacing = 1.0
    with tempfile.TemporaryDirectory() as t:
        _image(doc, Path(t))
    doc.add_paragraph("Figure 1. First result.", style="Caption")
    with tempfile.TemporaryDirectory() as t:
        _image(doc, Path(t))  # FIG.MISSING_CAPTION: no caption
    with tempfile.TemporaryDirectory() as t:
        _image(doc, Path(t))
    doc.add_paragraph("Figure 3. Third result.", style="Caption")  # FIG.NUMBERING: 1 -> 3
    doc.add_paragraph(
        "Table 1. Never referenced in the text.", style="Caption"
    )  # TBL.NOT_REFERENCED
    t = doc.add_table(rows=1, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "a", "b"
    for _ in range(3):  # LAYOUT.EMPTY_PARAGRAPHS
        doc.add_paragraph("")
    doc.add_heading("2. Results", level=1)  # STRUCT.HEADING_NUMBERING: "2." repeated
    doc.add_paragraph(BODY)
    new_sec = doc.add_section()
    _margins(new_sec, 1.0)
    doc.add_heading("3. Conclusion", level=1)
    doc.add_paragraph(BODY)
    doc.add_heading("References", level=1)
    doc.add_paragraph("[2] Out of order reference, 2018.")
    doc.add_paragraph("[1] First reference, 2017.")
    doc.save(str(path))
    return path


def build_clean_deck(path: Path) -> Path:
    prs = Presentation()
    prs.slide_width, prs.slide_height = PInches(13.333), PInches(7.5)
    s = prs.slides.add_slide(prs.slide_layouts[0])
    s.shapes.title.text = "Document Quality Review"
    s.placeholders[1].text = "Project status, March"
    for title, bullets in [
        ("Goals", ["Measure structure", "Validate formatting"]),
        ("Results", ["120 documents checked", "Most issues fixed"]),
    ]:
        s = prs.slides.add_slide(prs.slide_layouts[1])
        s.shapes.title.text = title
        tf = s.placeholders[1].text_frame
        tf.text = bullets[0]
        for b in bullets[1:]:
            tf.add_paragraph().text = b
        s.notes_slide.notes_text_frame.text = f"Speaker notes for {title}."
    prs.save(str(path))
    return path


def build_overflow_deck(path: Path) -> Path:
    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[5])
    s.shapes.title.text = "Too Much Text"
    box = s.shapes.add_textbox(PInches(1), PInches(5.5), PInches(4), PInches(1))
    tf = box.text_frame
    tf.word_wrap = True
    tf.text = " ".join(["This sentence is far too long for its small box."] * 14)
    for r in tf.paragraphs[0].runs:
        r.font.size = PPt(20)
    off = s.shapes.add_textbox(
        PInches(8.5), PInches(1), PInches(3), PInches(1)
    )  # off the 10in slide
    off.text_frame.text = "Off-slide text"
    s2 = prs.slides.add_slide(prs.slide_layouts[5])
    s2.shapes.title.text = "Mixed fonts"
    b2 = s2.shapes.add_textbox(PInches(1), PInches(2), PInches(6), PInches(1))
    b2.text_frame.text = "Small grey text"
    b2.text_frame.paragraphs[0].runs[0].font.size = PPt(9)
    prs.save(str(path))
    return path


def to_pdf(src: Path, out_dir: Path) -> Path:
    """Convert with LibreOffice (headless) — the same renderer the app uses."""
    profile = Path(tempfile.mkdtemp(prefix="lo-profile-"))
    try:
        subprocess.run(
            [
                shutil.which("soffice") or "soffice",
                "--headless",
                "--norestore",
                f"-env:UserInstallation=file://{profile}",
                "--convert-to",
                "pdf",
                "--outdir",
                str(out_dir),
                str(src),
            ],
            check=True,
            capture_output=True,
            timeout=180,
        )
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    return out_dir / (src.stem + ".pdf")


def build_all(out: Path) -> dict[str, Path]:
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "clean_docx": build_clean_report(out / "clean_report.docx"),
        "defective_docx": build_defective_report(out / "defective_report.docx"),
        "clean_pptx": build_clean_deck(out / "clean_deck.pptx"),
        "overflow_pptx": build_overflow_deck(out / "overflow_deck.pptx"),
    }
    files["clean_pdf"] = to_pdf(files["clean_docx"], out)
    files["defective_pdf"] = to_pdf(files["defective_docx"], out)
    return files


if __name__ == "__main__":
    import sys

    for k, v in build_all(Path(sys.argv[1] if len(sys.argv) > 1 else "fixtures-out")).items():
        print(k, v)
