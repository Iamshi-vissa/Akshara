"""DOCX → ADM importer (python-docx + lxml).

Effective formatting is resolved the way Word does it, in increasing priority:
``docDefaults`` → paragraph style chain (``basedOn``) → character style chain → direct
formatting. Theme fonts (``asciiTheme="minorHAnsi"``) are resolved through ``theme1.xml``.
Macros are never present here: the upload gate rejects macro-enabled packages.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from docx import Document as open_docx
from docx.document import Document as DocxDocument
from docx.oxml.ns import qn
from docx.styles.style import BaseStyle
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph
from lxml import etree

from app.domain.adm.model import (
    AdmDocument,
    Block,
    Caption,
    Figure,
    HeaderFooter,
    Heading,
    Margins,
    Metadata,
    PageBreak,
    PageSetup,
    ParaFmt,
    Paragraph,
    Run,
    RunFmt,
    Source,
    Table,
    TableCell,
)
from app.domain.adm.outline import count_words, section_role

EMU_PER_PT = 12700
CAPTION_RE = re.compile(
    r"^\s*(?P<label>Fig(?:ure)?\.?|Table|TABLE|Equation|Eq\.)\s*(?P<num>[0-9IVXLC]+[a-z]?)\s*[.:\-–—]?",  # noqa: RUF001
    re.IGNORECASE,
)
NUMBER_LABEL_RE = re.compile(r"^\s*((?:\d+(?:\.\d+)*\.?)|(?:[IVXLC]+\.)|(?:[A-Z]\.))\s+\S")
ALIGN = {
    "left": "left",
    "start": "left",
    "center": "center",
    "right": "right",
    "end": "right",
    "both": "justify",
    "distribute": "justify",
}


def _pt(twips: str | None) -> float | None:
    return round(int(twips) / 20, 2) if twips not in (None, "") else None


class _StyleResolver:
    """Resolves effective run/paragraph properties from raw OOXML."""

    def __init__(self, doc: DocxDocument) -> None:
        self.doc = doc
        styles_el = doc.styles.element
        self.styles_by_id: dict[str, Any] = {s.get(qn("w:styleId")): s for s in styles_el.findall(qn("w:style"))}
        defaults = styles_el.find(qn("w:docDefaults"))
        self.default_rpr = defaults.find(f"{qn('w:rPrDefault')}/{qn('w:rPr')}") if defaults is not None else None
        self.default_ppr = defaults.find(f"{qn('w:pPrDefault')}/{qn('w:pPr')}") if defaults is not None else None
        self.theme_fonts = self._theme_fonts()
        default_para = next(
            (
                s
                for s in self.styles_by_id.values()
                if s.get(qn("w:type")) == "paragraph" and s.get(qn("w:default")) in ("1", "true")
            ),
            None,
        )
        self.default_para_style_id = default_para.get(qn("w:styleId")) if default_para is not None else None

    def _theme_fonts(self) -> dict[str, str]:
        fonts: dict[str, str] = {}
        try:
            part = self.doc.part.part_related_by(
                "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme"
            )
            root = etree.fromstring(part.blob, parser=etree.XMLParser(resolve_entities=False))
        except (KeyError, ValueError, etree.XMLSyntaxError):
            return fonts
        a = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
        for kind in ("major", "minor"):
            el = root.find(f".//{a}{kind}Font/{a}latin")
            if el is not None and el.get("typeface"):
                fonts[kind] = el.get("typeface")
        return fonts

    def _chain(self, style_id: str | None) -> list[Any]:
        chain: list[Any] = []
        seen: set[str] = set()
        while style_id and style_id not in seen and style_id in self.styles_by_id:
            seen.add(style_id)
            st = self.styles_by_id[style_id]
            chain.append(st)
            based = st.find(qn("w:basedOn"))
            style_id = based.get(qn("w:val")) if based is not None else None
        return list(reversed(chain))  # base first

    # --- run properties -----------------------------------------------------------------
    def _apply_rpr(self, rpr: Any, acc: dict[str, Any]) -> None:
        if rpr is None:
            return
        fonts = rpr.find(qn("w:rFonts"))
        if fonts is not None:
            if fonts.get(qn("w:ascii")):
                acc["font_family"] = fonts.get(qn("w:ascii"))
            elif fonts.get(qn("w:asciiTheme")):
                theme = fonts.get(qn("w:asciiTheme"), "")
                key = "major" if theme.startswith("major") else "minor"
                if key in self.theme_fonts:
                    acc["font_family"] = self.theme_fonts[key]
        sz = rpr.find(qn("w:sz"))
        if sz is not None and sz.get(qn("w:val")):
            acc["size_pt"] = int(sz.get(qn("w:val"))) / 2
        for tag, key in (("w:b", "bold"), ("w:i", "italic")):
            el = rpr.find(qn(tag))
            if el is not None:
                acc[key] = el.get(qn("w:val"), "true") not in ("0", "false", "off")
        u = rpr.find(qn("w:u"))
        if u is not None:
            acc["underline"] = u.get(qn("w:val"), "single") != "none"
        color = rpr.find(qn("w:color"))
        if color is not None and color.get(qn("w:val")) not in (None, "auto"):
            acc["color"] = "#" + color.get(qn("w:val")).upper()

    def para_style_id(self, p: DocxParagraph) -> str | None:
        ppr = p._p.pPr
        if ppr is not None and ppr.pStyle is not None:
            return str(ppr.pStyle.val)
        return self.default_para_style_id

    def run_fmt(self, p: DocxParagraph, r_el: Any) -> RunFmt:
        acc: dict[str, Any] = {}
        self._apply_rpr(self.default_rpr, acc)
        for st in self._chain(self.para_style_id(p)):
            self._apply_rpr(st.find(qn("w:rPr")), acc)
        rpr = r_el.find(qn("w:rPr"))
        if rpr is not None:
            rstyle = rpr.find(qn("w:rStyle"))
            if rstyle is not None:
                for st in self._chain(rstyle.get(qn("w:val"))):
                    self._apply_rpr(st.find(qn("w:rPr")), acc)
            self._apply_rpr(rpr, acc)
        return RunFmt(**acc)

    # --- paragraph properties -------------------------------------------------------------
    def _apply_ppr(self, ppr: Any, acc: dict[str, Any]) -> None:
        if ppr is None:
            return
        jc = ppr.find(qn("w:jc"))
        if jc is not None and jc.get(qn("w:val")) in ALIGN:
            acc["alignment"] = ALIGN[jc.get(qn("w:val"))]
        sp = ppr.find(qn("w:spacing"))
        if sp is not None:
            if sp.get(qn("w:before")) is not None:
                acc["space_before_pt"] = _pt(sp.get(qn("w:before")))
            if sp.get(qn("w:after")) is not None:
                acc["space_after_pt"] = _pt(sp.get(qn("w:after")))
            line = sp.get(qn("w:line"))
            if line is not None:
                rule = sp.get(qn("w:lineRule"), "auto")
                if rule == "auto":
                    acc["line_spacing"] = round(int(line) / 240, 2)
                    acc["line_spacing_pt"] = None
                else:
                    acc["line_spacing_pt"] = _pt(line)
                    acc["line_spacing"] = None
        ind = ppr.find(qn("w:ind"))
        if ind is not None:
            left = ind.get(qn("w:left")) or ind.get(qn("w:start"))
            if left is not None:
                acc["indent_left_pt"] = _pt(left)
            right = ind.get(qn("w:right")) or ind.get(qn("w:end"))
            if right is not None:
                acc["indent_right_pt"] = _pt(right)
            if ind.get(qn("w:firstLine")) is not None:
                acc["indent_first_pt"] = _pt(ind.get(qn("w:firstLine")))
            elif ind.get(qn("w:hanging")) is not None:
                acc["indent_first_pt"] = -(_pt(ind.get(qn("w:hanging"))) or 0)

    def para_fmt(self, p: DocxParagraph) -> ParaFmt:
        acc: dict[str, Any] = {}
        self._apply_ppr(self.default_ppr, acc)
        for st in self._chain(self.para_style_id(p)):
            self._apply_ppr(st.find(qn("w:pPr")), acc)
        self._apply_ppr(p._p.pPr, acc)
        acc.setdefault("alignment", "left")
        acc.setdefault("line_spacing", 1.0 if "line_spacing_pt" not in acc else None)
        acc.setdefault("space_before_pt", 0.0)
        acc.setdefault("space_after_pt", 0.0)
        return ParaFmt(**acc)

    def outline_level(self, p: DocxParagraph) -> int | None:
        for el in [p._p.pPr] + [st.find(qn("w:pPr")) for st in reversed(self._chain(self.para_style_id(p)))]:
            if el is None:
                continue
            ol = el.find(qn("w:outlineLvl"))
            if ol is not None and ol.get(qn("w:val")) is not None:
                lvl = int(ol.get(qn("w:val")))
                return lvl + 1 if lvl < 9 else None
        return None

    def is_numbered(self, p: DocxParagraph) -> bool:
        for el in [p._p.pPr] + [st.find(qn("w:pPr")) for st in reversed(self._chain(self.para_style_id(p)))]:
            if el is not None and el.find(qn("w:numPr")) is not None:
                num = el.find(qn("w:numPr")).find(qn("w:numId"))
                return not (num is not None and num.get(qn("w:val")) == "0")
        return False


def _style_name(style: BaseStyle | None) -> str | None:
    return style.name if style is not None else None


def _has_page_field(el: Any) -> bool:
    xml = etree.tostring(el, encoding="unicode")
    return bool(re.search(r"(?:instr=\"\s*PAGE\b|<w:instrText[^>]*>\s*PAGE\b)", xml))


def _header_footers(section: Any) -> tuple[list[HeaderFooter], list[HeaderFooter]]:
    headers: list[HeaderFooter] = []
    footers: list[HeaderFooter] = []
    for kind, part, out in (
        ("header", section.header, headers),
        ("footer", section.footer, footers),
    ):
        if part.is_linked_to_previous:  # no own definition: inherits (or nothing, for section 1)
            continue
        text = "\n".join(p.text for p in part.paragraphs).strip()
        has_num = _has_page_field(part._element)
        if text or has_num:
            out.append(HeaderFooter(kind=kind, text=text, has_page_number=has_num))
    return headers, footers


def _margins(sec: Any) -> Margins | None:
    vals = (sec.top_margin, sec.bottom_margin, sec.left_margin, sec.right_margin)
    if any(v is None for v in vals):
        return None
    top, bottom, left, right = (round(v.pt, 1) for v in vals)
    return Margins(top=top, bottom=bottom, left=left, right=right)


def import_docx(path: Path) -> AdmDocument:
    doc = open_docx(str(path))
    res = _StyleResolver(doc)
    body: list[Block] = []
    warnings: list[str] = []
    in_references = False
    pending_caption_targets: list[int] = []  # indices of figures/tables awaiting a caption
    last_caption_idx: int | None = None

    def add(block: Block) -> None:
        body.append(block)

    children = list(doc.element.body.iterchildren())
    for idx, child in enumerate(children):
        tag = etree.QName(child).localname
        src = Source(fmt="docx", index=idx)
        if tag == "tbl":
            tbl = DocxTable(child, doc)
            rows = []
            for row in tbl.rows:
                cells = []
                seen: set[int] = set()
                for cell in row.cells:
                    if id(cell._tc) in seen:
                        continue
                    seen.add(id(cell._tc))
                    grid = cell._tc.tcPr.gridSpan if cell._tc.tcPr is not None else None
                    cells.append(
                        TableCell(
                            text=cell.text.strip(),
                            paragraphs=len(cell.paragraphs),
                            col_span=int(grid.val) if grid is not None else 1,
                        )
                    )
                rows.append(cells)
            widths = [c.width.pt for c in tbl.columns if c.width is not None]
            tnode = Table(
                id=f"t{idx}",
                source=src,
                rows=rows,
                width_pt=round(sum(widths), 1) if widths else None,
            )
            add(tnode)
            pending_caption_targets.append(len(body) - 1)
            prev_cap = body[last_caption_idx] if last_caption_idx is not None else None
            if isinstance(prev_cap, Caption) and prev_cap.target_kind == "table" and prev_cap.target_id is None:
                prev_cap.target_id, prev_cap.position, tnode.caption_id = (
                    tnode.id,
                    "above",
                    prev_cap.id,
                )
                pending_caption_targets.pop()
            continue
        if tag != "p":
            continue

        p = DocxParagraph(child, doc)
        style = _style_name(p.style) if p.style is not None else None
        runs: list[Run] = []
        figure_sizes: list[tuple[float | None, float | None, str | None]] = []
        page_break = False
        for r_el in child.iter(qn("w:r")):
            texts = []
            for t in r_el.iterchildren():
                name = etree.QName(t).localname
                if name == "t":
                    texts.append(t.text or "")
                elif name == "tab":
                    texts.append("\t")
                elif name == "br":
                    if t.get(qn("w:type")) == "page":
                        page_break = True
                    else:
                        texts.append("\n")
                elif name == "drawing":
                    ext = t.find(".//{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}extent")
                    doc_pr = t.find(".//{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}docPr")
                    w = int(ext.get("cx")) / EMU_PER_PT if ext is not None else None
                    h = int(ext.get("cy")) / EMU_PER_PT if ext is not None else None
                    alt = (doc_pr.get("descr") or None) if doc_pr is not None else None
                    figure_sizes.append((w, h, alt))
            text = "".join(texts)
            if text:
                runs.append(Run(text=text, fmt=res.run_fmt(p, r_el)))
        fmt = res.para_fmt(p)
        text = "".join(r.text for r in runs)
        stripped = text.strip()

        for w, h, alt in figure_sizes:
            fig = Figure(
                id=f"f{idx}.{len(body)}",
                source=src,
                width_pt=w and round(w, 1),
                height_pt=h and round(h, 1),
                alt_text=alt,
            )
            add(fig)
            pending_caption_targets.append(len(body) - 1)
            prev_c = body[last_caption_idx] if last_caption_idx is not None else None
            if (
                isinstance(prev_c, Caption)
                and prev_c.target_kind == "figure"
                and prev_c.target_id is None
                and not stripped
            ):
                prev_c.target_id, prev_c.position, fig.caption_id = fig.id, "above", prev_c.id

        if not stripped and not figure_sizes:
            if not page_break:
                add(Paragraph(id=f"p{idx}", source=src, runs=runs, style_ref=style, fmt=fmt, role="empty"))
        elif stripped:
            level = res.outline_level(p)
            if style and style.lower() == "title":
                level = 0
            elif level is None and style:
                m = re.match(r"heading\s*(\d)", style, re.IGNORECASE)
                if m:
                    level = int(m.group(1))
            cap_m = CAPTION_RE.match(stripped)
            if level is not None and len(stripped) < 300:
                num = NUMBER_LABEL_RE.match(stripped)
                node: Block = Heading(
                    id=f"p{idx}",
                    source=src,
                    runs=runs,
                    style_ref=style,
                    fmt=fmt,
                    level=level,
                    numbering_label=num.group(1).rstrip(".") if num else None,
                    auto_numbered=res.is_numbered(p),
                )
                role = section_role(stripped)
                in_references = role == "references"
            elif cap_m and (style == "Caption" or len(stripped) < 400):
                label = cap_m.group("label")
                kind = (
                    "table"
                    if label.lower().startswith("tab")
                    else ("equation" if label.lower().startswith("eq") else "figure")
                )
                cap_node = Caption(
                    id=f"p{idx}",
                    source=src,
                    runs=runs,
                    style_ref=style,
                    fmt=fmt,
                    target_kind=kind,
                    label=label,
                    number=cap_m.group("num"),
                )
                node = cap_node
                # A caption directly after its figure/table is "below".
                prev = body[pending_caption_targets[-1]] if pending_caption_targets else None
                if (
                    prev is not None
                    and pending_caption_targets[-1] == len(body) - 1
                    and (
                        (kind == "figure" and isinstance(prev, Figure)) or (kind == "table" and isinstance(prev, Table))
                    )
                ):
                    cap_node.target_id, cap_node.position = prev.id, "below"
                    prev.caption_id = cap_node.id
                    pending_caption_targets.pop()
                last_caption_idx = len(body)
            else:
                role = "reference_entry" if in_references else "body"
                if not in_references:
                    if (style and style.lower().startswith("list")) or res.is_numbered(p):
                        role = "list_item"
                    elif style and style.lower() == "subtitle":
                        role = "subtitle"
                node = Paragraph(id=f"p{idx}", source=src, runs=runs, style_ref=style, fmt=fmt, role=role)
            add(node)
        if page_break:
            add(PageBreak(id=f"b{idx}", source=src))

    # Page setup per DOCX section.
    setups: list[PageSetup] = []
    for i, sec in enumerate(doc.sections):
        w, h = sec.page_width, sec.page_height
        if w is None or h is None:
            warnings.append(f"Section {i + 1} has no page size; Word defaults apply.")
            continue
        cols_el = sec._sectPr.find(qn("w:cols"))
        cols = int(cols_el.get(qn("w:num"), "1")) if cols_el is not None else 1
        headers, footers = _header_footers(sec)
        setups.append(
            PageSetup(
                id=f"ps{i}",
                width_pt=round(w.pt, 1),
                height_pt=round(h.pt, 1),
                orientation="landscape" if w > h else "portrait",
                margins=_margins(sec),
                columns=cols,
                headers=headers,
                footers=footers,
            )
        )

    props = doc.core_properties
    full_text = "\n".join(b.text for b in body)
    meta = Metadata(
        title=(props.title or None),
        authors=[a.strip() for a in re.split(r"[;,]", props.author or "") if a.strip()],
        subject=props.subject or None,
        keywords=[k.strip() for k in re.split(r"[;,]", props.keywords or "") if k.strip()],
        language=props.language or None,
        word_count=count_words(full_text),
    )
    return AdmDocument(source_format="docx", metadata=meta, page_setups=setups, body=body, warnings=warnings)
