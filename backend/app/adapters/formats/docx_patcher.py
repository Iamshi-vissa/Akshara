"""Apply change operations to an original DOCX (patch-based export, decision D6).

The original package is opened with python-docx and only the targeted XML is changed, so
everything AKSHARA does not model (comments, fields, content controls, custom XML) survives.
Node ids map to body elements through their source index, resolved *before* any mutation,
so deleting or reordering paragraphs cannot shift later edits onto the wrong element.
"""

from __future__ import annotations

import copy
import io
import re
from pathlib import Path
from typing import Any

from docx import Document as open_docx
from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt
from docx.text.paragraph import Paragraph as DocxParagraph

from app.domain.adm.model import AdmDocument
from app.domain.changes import (
    AddPageNumbers,
    DeleteBlocks,
    Operation,
    ReplaceText,
    SetHeadingLevel,
    SetPageSetup,
    SetParaFmt,
    SetRunFmt,
    SortReferences,
)

ALIGN = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
}
PAPER_PT = {"Letter": (612.0, 792.0), "A4": (595.3, 841.9)}


class PatchError(Exception):
    """An operation could not be applied safely; nothing is written."""


def _set_fonts(rpr: Any, family: str) -> None:
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rpr.insert(0, fonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        fonts.set(qn(attr), family)
    for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:cstheme", "w:eastAsiaTheme"):
        if fonts.get(qn(attr)) is not None:
            del fonts.attrib[qn(attr)]


def _page_field_paragraph(par: DocxParagraph) -> None:
    run = par.add_run()
    for kind, text in (("begin", None), (None, " PAGE "), ("separate", None), (None, "1"), ("end", None)):
        if kind:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), kind)
            run._r.append(el)
        elif text == " PAGE ":
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = text
            run._r.append(el)
        else:
            t = OxmlElement("w:t")
            t.text = text
            run._r.append(t)


def _sort_key(text: str, order: str) -> tuple[int, str]:
    if order == "numeric":
        m = re.match(r"^\s*\[?(\d+)", text)
        return (int(m.group(1)) if m else 10**6, text)
    return (0, re.sub(r"[^a-z]", "", text.lower()))


def apply_docx(src: Path, adm: AdmDocument, ops: list[Operation]) -> bytes:
    doc = open_docx(str(src))
    body = doc.element.body
    children = list(body.iterchildren())
    by_id: dict[str, Any] = {}
    for node in adm.body:
        if node.source.index is not None and node.source.index < len(children):
            by_id[node.id] = children[node.source.index]

    def element(node_id: str) -> Any:
        if node_id not in by_id:
            raise PatchError(f"Element {node_id} not found in the original document.")
        return by_id[node_id]

    def para(node_id: str) -> DocxParagraph:
        el = element(node_id)
        if el.tag != qn("w:p"):
            raise PatchError(f"Element {node_id} is not a paragraph.")
        return DocxParagraph(el, doc)

    sections = list(doc.sections)
    for op in ops:
        if isinstance(op, SetPageSetup):
            targets = (
                sections
                if op.page_setup_ids == "all"
                else [
                    sections[int(i[2:])] for i in op.page_setup_ids if i.startswith("ps") and int(i[2:]) < len(sections)
                ]
            )
            for sec in targets:
                for side, value in (op.margins_pt or {}).items():
                    setattr(sec, f"{side}_margin", Pt(value))
                if op.paper:
                    w, h = PAPER_PT[op.paper]
                    landscape = sec.orientation == WD_ORIENT.LANDSCAPE
                    sec.page_width, sec.page_height = (Pt(h), Pt(w)) if landscape else (Pt(w), Pt(h))
                if op.columns:
                    sect_pr = sec._sectPr
                    cols = sect_pr.find(qn("w:cols"))
                    if cols is None:
                        cols = OxmlElement("w:cols")
                        sect_pr.append(cols)
                    cols.set(qn("w:num"), str(op.columns))
                    cols.set(qn("w:space"), str(int(0.25 * 1440)))
        elif isinstance(op, SetParaFmt):
            for nid in op.node_ids:
                pf = para(nid).paragraph_format
                if op.line_spacing is not None:
                    pf.line_spacing = op.line_spacing
                if op.alignment is not None:
                    pf.alignment = ALIGN[op.alignment]
                if op.space_before_pt is not None:
                    pf.space_before = Pt(op.space_before_pt)
                if op.space_after_pt is not None:
                    pf.space_after = Pt(op.space_after_pt)
                if op.indent_first_pt is not None:
                    pf.first_line_indent = Pt(op.indent_first_pt)
        elif isinstance(op, SetRunFmt):
            for nid in op.node_ids:
                p = para(nid)
                for r in p.runs:
                    rpr = r._r.get_or_add_rPr()
                    if op.font_family:
                        _set_fonts(rpr, op.font_family)
                    if op.size_pt:
                        r.font.size = Pt(op.size_pt)
                    if op.bold is not None:
                        r.font.bold = op.bold
        elif isinstance(op, SetHeadingLevel):
            p = para(op.node_id)
            name = f"Heading {op.level}"
            try:
                p.style = doc.styles[name]
            except KeyError as exc:
                raise PatchError(f"The document has no “{name}” style.") from exc
            ppr = p._p.pPr
            if ppr is not None and ppr.find(qn("w:outlineLvl")) is not None:
                ppr.remove(ppr.find(qn("w:outlineLvl")))
        elif isinstance(op, ReplaceText):
            p = para(op.node_id)
            if p.text.strip() != op.before.strip():
                raise PatchError("The paragraph changed since this edit was proposed.")
            runs = p.runs
            if not runs:
                p.add_run(op.after)
            else:
                runs[0].text = op.after  # keeps the first run's formatting
                for r in runs[1:]:
                    r._r.getparent().remove(r._r)
        elif isinstance(op, DeleteBlocks):
            for nid in op.node_ids:
                el = element(nid)
                if el.getparent() is not None:
                    el.getparent().remove(el)
        elif isinstance(op, AddPageNumbers):
            for i, sec in enumerate(sections):
                part = sec.header if op.position.startswith("header") else sec.footer
                if i > 0 and part.is_linked_to_previous:
                    continue
                part.is_linked_to_previous = False
                par = (
                    part.paragraphs[0]
                    if part.paragraphs and not part.paragraphs[0].text.strip()
                    else part.add_paragraph()
                )
                par.alignment = WD_ALIGN_PARAGRAPH.RIGHT if op.position.endswith("right") else WD_ALIGN_PARAGRAPH.CENTER
                _page_field_paragraph(par)
        elif isinstance(op, SortReferences):
            els = [element(n) for n in op.node_ids]
            if not els:
                continue
            parent = els[0].getparent()
            members = set(map(id, els))
            # Anchor = the nearest preceding sibling that is not itself one of the entries.
            first = min(els, key=lambda e: list(parent).index(e))
            anchor = first.getprevious()
            while anchor is not None and id(anchor) in members:
                anchor = anchor.getprevious()
            texts = {id(e): DocxParagraph(e, doc).text for e in els}
            ordered = sorted(els, key=lambda e: _sort_key(texts[id(e)], op.order))
            for e in els:
                parent.remove(e)
            insert_at = list(parent).index(anchor) + 1 if anchor is not None else 0
            for k, e in enumerate(ordered):
                parent.insert(insert_at + k, e)
        else:
            raise PatchError(f"Operation {op.op} is not supported for Word documents.")

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def deep_copy_xml(el: Any) -> Any:  # used by tests to compare untouched parts
    return copy.deepcopy(el)
