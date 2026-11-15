"""PDF → ADM importer (PyMuPDF).

PDF is a layout format: it has no paragraphs, headings or styles, only positioned glyphs.
Structure is therefore **inferred**, and every inferred value is marked ``fidelity="inferred"``
so downstream rules treat it with lower confidence (ARCHITECTURE.md §10 R2):

* paragraphs = PyMuPDF text blocks;
* heading level = rank of font sizes larger than the body size (body = most common size);
* margins = the tightest text/image box seen across pages;
* running headers/footers = short lines repeated in the top/bottom band of most pages.
PDF content is never executed; only text and geometry are read.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pymupdf

from app.domain.adm.model import (
    AdmDocument,
    Block,
    Caption,
    Figure,
    HeaderFooter,
    Heading,
    Margins,
    Metadata,
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

CAPTION_RE = re.compile(
    r"^\s*(?P<label>Fig(?:ure)?\.?|Table|TABLE)\s*(?P<num>[0-9IVXLC]+[a-z]?)\s*[.:\-–—]",  # noqa: RUF001
    re.IGNORECASE,
)
NUMBER_LABEL_RE = re.compile(r"^\s*((?:\d+(?:\.\d+)*\.?)|(?:[IVXLC]+\.)|(?:[A-Z]\.))\s+\S")
REF_LABEL_RE = re.compile(r"^\s*(\[\d+\]|\d+\.\s)")  # a new reference-list entry
BAND = 0.07  # top/bottom fraction of the page treated as header/footer area
MAX_TABLE_PAGES = 60


def _norm_font(name: str) -> str:
    base = name.split("+", 1)[-1]  # strip subset prefix ABCDEF+
    base = re.sub(
        r"[-,](Bold|Italic|Oblique|BoldItalic|BoldOblique|Regular|Roman|MT|PS|Semibold|Light|Medium).*$",
        "",
        base,
        flags=re.IGNORECASE,
    )
    base = re.sub(r"(PSMT|MT|PS)$", "", base)
    base = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", base)
    return base.strip()


def _style_key(block: dict) -> tuple[str, float, bool]:  # type: ignore[type-arg]
    s = max(block["spans"], key=lambda sp: len(sp["text"]))
    return (_norm_font(s["font"]), round(s["size"], 1), bool(s["flags"] & 16))


def _merge_lines(blocks: list[dict]) -> list[dict]:  # type: ignore[type-arg]
    """Join consecutive text blocks that are lines of one paragraph.

    Word processors exported with wide line spacing often emit one block per line. A block
    continues the previous one when it has the same style, starts at the same left edge (or
    the paragraph's first-line indent), sits directly below it, and the previous block's last
    line runs (almost) to the right edge, i.e. the paragraph had not ended.
    """
    if not blocks:
        return blocks
    right_edge = max(b["bbox"][2] for b in blocks)
    out = [blocks[0]]
    for b in blocks[1:]:
        prev = out[-1]
        px0, py0, px1, py1 = prev["bbox"]
        x0, y0, x1, y1 = b["bbox"]
        size = _style_key(b)[1]
        continues = (
            not prev["in_band"]
            and not b["in_band"]
            and _style_key(prev) == _style_key(b)
            and 0 <= y0 - py1 < size * 2.2
            and abs(x0 - min(px0, x0)) < size * 3
            and px1 >= right_edge - size * 2.5
            and not CAPTION_RE.match(b["text"])
            and not REF_LABEL_RE.match(b["text"])
        )
        if continues:
            prev["text"] = prev["text"] + " " + b["text"]
            prev["spans"] = prev["spans"] + b["spans"]
            prev["lines"] += b["lines"]
            prev["bbox"] = (min(px0, x0), py0, max(px1, x1), y1)
        else:
            out.append(b)
    return out


def import_pdf(path: Path) -> AdmDocument:
    doc = pymupdf.open(str(path))
    try:
        return _import(doc)
    finally:
        doc.close()


def _import(doc: pymupdf.Document) -> AdmDocument:
    warnings = ["PDF structure is inferred from layout; headings and spacing are estimates."]
    pages = []
    size_chars: Counter[float] = Counter()
    font_chars: Counter[str] = Counter()
    band_lines: Counter[str] = Counter()

    for pno in range(doc.page_count):
        page = doc[pno]
        w, h = page.rect.width, page.rect.height
        data = page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)
        blocks = []
        for b in data["blocks"]:
            if b.get("type") != 0:
                continue
            spans = [s for line in b["lines"] for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            text = "\n".join("".join(s["text"] for s in line["spans"]) for line in b["lines"]).strip()
            for s in spans:
                n = len(s["text"].strip())
                size_chars[round(s["size"], 1)] += n
                font_chars[_norm_font(s["font"])] += n
            x0, y0, x1, y1 = b["bbox"]
            in_band = y1 < h * BAND or y0 > h * (1 - BAND)
            if in_band:
                band_lines[re.sub(r"\d+", "#", text)] += 1
            blocks.append(
                {
                    "bbox": (x0, y0, x1, y1),
                    "text": text,
                    "spans": spans,
                    "lines": len(b["lines"]),
                    "in_band": in_band,
                }
            )
        images = [i["bbox"] for i in page.get_image_info() if i["bbox"][2] - i["bbox"][0] > 20]
        pages.append({"w": w, "h": h, "blocks": _merge_lines(blocks), "images": images, "page": page})

    body_size = size_chars.most_common(1)[0][0] if size_chars else 0.0
    repeated = {t for t, n in band_lines.items() if n >= max(2, doc.page_count * 0.5)}

    def heading_like(b: dict) -> bool:  # type: ignore[type-arg]
        text = b["text"].replace("\n", " ").strip()
        if len(text) >= 160 or b["lines"] > 3 or CAPTION_RE.match(text):
            return False
        _, size, bold = _style_key(b)
        larger = size >= body_size * 1.12
        numbered = NUMBER_LABEL_RE.match(text) is not None
        named = section_role(text) != "unknown" and len(text) < 60
        return larger or (bold and (numbered or named) and len(text) < 100)

    cand_sizes = sorted(
        {_style_key(b)[1] for pg in pages for b in pg["blocks"] if not b["in_band"] and heading_like(b)},
        reverse=True,
    )
    first_page_heads = [b for b in pages[0]["blocks"] if not b["in_band"] and heading_like(b)] if pages else []
    title_size = (
        cand_sizes[0]
        if first_page_heads and len(cand_sizes) > 1 and _style_key(first_page_heads[0])[1] == cand_sizes[0]
        else None
    )
    rank_sizes = [s for s in cand_sizes if s != title_size]

    def level_for(b: dict, is_first: bool) -> int:  # type: ignore[type-arg]
        size = _style_key(b)[1]
        if title_size is not None and size == title_size and is_first:
            return 0
        num = NUMBER_LABEL_RE.match(b["text"])
        if num and re.fullmatch(r"\d+(\.\d+)*\.?", num.group(1)):
            return min(num.group(1).rstrip(".").count(".") + 1, 6)
        return min(rank_sizes.index(size) + 1 if size in rank_sizes else 1, 6)

    body: list[Block] = []
    in_refs = False
    headers_seen: list[HeaderFooter] = []
    footers_seen: list[HeaderFooter] = []
    min_left = min_top = min_right = min_bottom = None

    for pno, pg in enumerate(pages):
        w, h = pg["w"], pg["h"]
        for b in pg["blocks"]:
            x0, y0, x1, y1 = b["bbox"]
            norm = re.sub(r"\d+", "#", b["text"])
            if b["in_band"] and (norm in repeated or re.fullmatch(r"#|Page # (of #)?|- # -", norm.strip())):
                hf = HeaderFooter(
                    kind="header" if y1 < h / 2 else "footer",
                    text=b["text"],
                    has_page_number=bool(re.search(r"\d", b["text"])),
                )
                target = headers_seen if hf.kind == "header" else footers_seen
                if pno == 0 or not target:
                    target.append(hf)
                continue
            min_left = x0 if min_left is None else min(min_left, x0)
            min_top = y0 if min_top is None else min(min_top, y0)
            min_right = (w - x1) if min_right is None else min(min_right, w - x1)
            min_bottom = (h - y1) if min_bottom is None else min(min_bottom, h - y1)

            runs = [
                Run(
                    text=s["text"],
                    fmt=RunFmt(
                        font_family=_norm_font(s["font"]),
                        size_pt=round(s["size"], 1),
                        bold=bool(s["flags"] & 16) or "bold" in s["font"].lower(),
                        italic=bool(s["flags"] & 2) or "italic" in s["font"].lower(),
                        color=f"#{s['color']:06X}",
                    ),
                )
                for s in b["spans"]
            ]
            src = Source(fmt="pdf", page=pno, bbox=(round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)))
            nid = f"pg{pno}.{len(body)}"
            text = b["text"].replace("\n", " ").strip()
            fmt = ParaFmt(alignment=None)
            cap = CAPTION_RE.match(text)
            num = NUMBER_LABEL_RE.match(text)
            is_heading = heading_like(b)
            if cap:
                label = cap.group("label")
                body.append(
                    Caption(
                        id=nid,
                        source=src,
                        runs=runs,
                        fmt=fmt,
                        fidelity="inferred",
                        target_kind="table" if label.lower().startswith("tab") else "figure",
                        label=label,
                        number=cap.group("num"),
                    )
                )
            elif is_heading:
                level = level_for(b, is_first=not any(isinstance(x, Heading) for x in body))
                body.append(
                    Heading(
                        id=nid,
                        source=src,
                        runs=runs,
                        fmt=fmt,
                        fidelity="inferred",
                        level=level,
                        numbering_label=num.group(1).rstrip(".") if num else None,
                    )
                )
                in_refs = section_role(text) == "references"
            else:
                body.append(
                    Paragraph(
                        id=nid,
                        source=src,
                        runs=runs,
                        fmt=fmt,
                        fidelity="inferred",
                        role="reference_entry" if in_refs else "body",
                    )
                )
        page_start = next((i for i, n in enumerate(body) if n.source.page == pno), len(body))
        for i, (x0, y0, x1, y1) in enumerate(pg["images"]):
            fig = Figure(
                id=f"pg{pno}.img{i}",
                source=Source(fmt="pdf", page=pno, bbox=(x0, y0, x1, y1)),
                width_pt=round(x1 - x0, 1),
                height_pt=round(y1 - y0, 1),
            )
            # Insert in reading order (top to bottom) among this page's blocks.
            pos = len(body)
            for j in range(page_start, len(body)):
                bb = body[j].source.bbox
                if bb is not None and bb[1] > y0:
                    pos = j
                    break
            body.insert(pos, fig)
        if pno < MAX_TABLE_PAGES:
            try:
                for ti, tab in enumerate(pg["page"].find_tables().tables):
                    rows = [[TableCell(text=(c or "").strip()) for c in row] for row in tab.extract()]
                    bx = tab.bbox
                    body.append(
                        Table(
                            id=f"pg{pno}.tbl{ti}",
                            source=Source(fmt="pdf", page=pno, bbox=tuple(round(v, 1) for v in bx)),
                            rows=rows,
                            width_pt=round(bx[2] - bx[0], 1),
                        )
                    )
            except Exception:
                warnings.append(f"Table detection failed on page {pno + 1}.")
    if doc.page_count > MAX_TABLE_PAGES:
        warnings.append(f"Table detection covers the first {MAX_TABLE_PAGES} pages only.")

    # Group consecutive pages of the same size into page setups.
    setups: list[PageSetup] = []
    margins = (
        Margins(
            top=round(min_top, 1),
            bottom=round(min_bottom, 1),
            left=round(min_left, 1),
            right=round(min_right, 1),
        )
        if min_left is not None and min_top is not None and min_bottom is not None and min_right is not None
        else None
    )
    for pno, pg in enumerate(pages):
        w, h = round(pg["w"], 1), round(pg["h"], 1)
        if setups and setups[-1].width_pt == w and setups[-1].height_pt == h:
            setups[-1].last_page = pno
            continue
        setups.append(
            PageSetup(
                id=f"ps{len(setups)}",
                first_page=pno,
                last_page=pno,
                width_pt=w,
                height_pt=h,
                orientation="landscape" if w > h else "portrait",
                margins=margins,
                headers=headers_seen[:1],
                footers=footers_seen[:1],
                fidelity="inferred",
            )
        )

    md = doc.metadata or {}
    text = "\n".join(b.text for b in body)
    meta = Metadata(
        title=md.get("title") or None,
        authors=[a.strip() for a in re.split(r"[;,]", md.get("author") or "") if a.strip()],
        subject=md.get("subject") or None,
        keywords=[k.strip() for k in re.split(r"[;,]", md.get("keywords") or "") if k.strip()],
        page_count=doc.page_count,
        word_count=count_words(text),
    )
    if font_chars:
        warnings.append(f"Dominant font: {font_chars.most_common(1)[0][0]}, body size ≈ {body_size} pt.")
    return AdmDocument(source_format="pdf", metadata=meta, page_setups=setups, body=body, warnings=warnings)
