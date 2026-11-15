"""ADM node types.

Design rules (ARCHITECTURE.md §7.1):

* **Stable IDs.** Node ids derive from the source position (``p12``, ``t3``, ``s2.sh5``), so a
  formatting-only change produces the same ids in the next version.
* **Source anchors.** ``source`` records where a node came from, so patchers can find it again.
* **Effective formatting with fidelity.** Formatting values are resolved (style inheritance
  applied). ``fidelity`` says whether they were read exactly from the file, inferred (e.g. a
  PDF heading level guessed from font size) or unknown. ``None`` always means "unknown".
* **Origin.** ``original`` | ``edited`` | ``generated`` marks who wrote the text.
* Units: all lengths are points (1/72 in).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

ADM_SCHEMA_VERSION = "1.0"

Fidelity = Literal["exact", "inferred", "unknown"]
Origin = Literal["original", "edited", "generated"]
SourceFormat = Literal["docx", "pdf", "pptx", "generated"]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(_M):
    fmt: SourceFormat
    index: int | None = None  # block index in the body (docx) / paragraph index in a shape
    page: int | None = None  # 0-based page (pdf)
    bbox: tuple[float, float, float, float] | None = None  # x0, y0, x1, y1 in pt
    slide: int | None = None  # 0-based slide (pptx)
    shape_id: int | None = None


class RunFmt(_M):
    font_family: str | None = None
    size_pt: float | None = None
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None
    color: str | None = None  # "#RRGGBB"


class Mark(_M):
    kind: Literal["citation", "link", "xref"]
    value: str  # citation key text, href, or target node id


class Run(_M):
    text: str
    fmt: RunFmt = Field(default_factory=RunFmt)
    marks: list[Mark] = Field(default_factory=list)


class ParaFmt(_M):
    alignment: Literal["left", "center", "right", "justify"] | None = None
    line_spacing: float | None = None  # multiple of single spacing (1.0, 1.5, 2.0)
    line_spacing_pt: float | None = None  # exact/at-least spacing in pt, when used
    space_before_pt: float | None = None
    space_after_pt: float | None = None
    indent_first_pt: float | None = None
    indent_left_pt: float | None = None
    indent_right_pt: float | None = None


class _Node(_M):
    id: str
    source: Source
    origin: Origin = "original"


class _TextNode(_Node):
    runs: list[Run] = Field(default_factory=list)
    style_ref: str | None = None
    fmt: ParaFmt = Field(default_factory=ParaFmt)
    fidelity: Fidelity = "exact"

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)

    def dominant_run_fmt(self) -> RunFmt:
        """Formatting covering the most characters (ignores whitespace-only runs)."""
        weights: dict[tuple[object, ...], tuple[int, RunFmt]] = {}
        for r in self.runs:
            n = len(r.text.strip())
            if not n:
                continue
            key = (r.fmt.font_family, r.fmt.size_pt, r.fmt.bold, r.fmt.italic)
            prev = weights.get(key, (0, r.fmt))
            weights[key] = (prev[0] + n, r.fmt)
        if not weights:
            return self.runs[0].fmt if self.runs else RunFmt()
        return max(weights.values(), key=lambda w: w[0])[1]


ParagraphRole = Literal[
    "body",
    "title",
    "subtitle",
    "author",
    "abstract",
    "keywords",
    "list_item",
    "reference_entry",
    "quote",
    "code",
    "toc",
    "empty",
]


class Paragraph(_TextNode):
    type: Literal["paragraph"] = "paragraph"
    role: ParagraphRole = "body"
    list_level: int | None = None


class Heading(_TextNode):
    type: Literal["heading"] = "heading"
    level: int = Field(ge=0, le=9)  # 0 = document title
    numbering_label: str | None = None  # "2.1", "III", "A" when visible in text
    auto_numbered: bool = False  # numbered by the word processor (label not in text)


class Caption(_TextNode):
    type: Literal["caption"] = "caption"
    target_kind: Literal["figure", "table", "equation", "unknown"]
    label: str  # "Fig.", "Figure", "Table"
    number: str | None = None
    target_id: str | None = None
    position: Literal["above", "below", "unknown"] = "unknown"


class TableCell(_M):
    text: str
    paragraphs: int = 1
    col_span: int = 1


class Table(_Node):
    type: Literal["table"] = "table"
    rows: list[list[TableCell]]
    width_pt: float | None = None
    caption_id: str | None = None

    @property
    def text(self) -> str:
        return " | ".join(c.text for row in self.rows for c in row)


class Figure(_Node):
    type: Literal["figure"] = "figure"
    width_pt: float | None = None
    height_pt: float | None = None
    alt_text: str | None = None
    caption_id: str | None = None
    text: str = ""


class PageBreak(_Node):
    type: Literal["page_break"] = "page_break"
    text: str = ""


Block = Annotated[Paragraph | Heading | Caption | Table | Figure | PageBreak, Field(discriminator="type")]


class Margins(_M):
    top: float
    bottom: float
    left: float
    right: float


class HeaderFooter(_M):
    kind: Literal["header", "footer"]
    text: str
    has_page_number: bool = False


class PageSetup(_M):
    id: str
    first_page: int | None = None  # pdf page range, else None
    last_page: int | None = None
    width_pt: float
    height_pt: float
    orientation: Literal["portrait", "landscape"]
    margins: Margins | None = None
    columns: int | None = None
    headers: list[HeaderFooter] = Field(default_factory=list)
    footers: list[HeaderFooter] = Field(default_factory=list)
    fidelity: Fidelity = "exact"

    @property
    def paper(self) -> str:
        return paper_name(self.width_pt, self.height_pt)


def paper_name(w: float, h: float) -> str:
    short, long_ = sorted((w, h))
    for name, (pw, ph) in {
        "Letter": (612, 792),
        "A4": (595.3, 841.9),
        "Legal": (612, 1008),
        "A5": (419.5, 595.3),
    }.items():
        if abs(short - pw) <= 3 and abs(long_ - ph) <= 3:
            return name
    return "Custom"


class Shape(_M):
    id: str
    kind: Literal["text", "picture", "table", "other"]
    name: str = ""
    placeholder: str | None = None  # title, body, subtitle...
    bbox: tuple[float, float, float, float] | None = None  # x0, y0, x1, y1 in pt
    paragraphs: list[Paragraph] = Field(default_factory=list)
    autofit: Literal["none", "normal", "shape", "unknown"] = "unknown"

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.paragraphs)


class Slide(_M):
    id: str
    index: int
    layout: str | None = None
    title: str | None = None
    shapes: list[Shape] = Field(default_factory=list)
    notes: str = ""
    hidden: bool = False


class Metadata(_M):
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    subject: str | None = None
    keywords: list[str] = Field(default_factory=list)
    language: str | None = None
    page_count: int | None = None
    word_count: int = 0


class AdmDocument(_M):
    adm_schema_version: str = ADM_SCHEMA_VERSION
    source_format: SourceFormat
    metadata: Metadata = Field(default_factory=Metadata)
    page_setups: list[PageSetup] = Field(default_factory=list)
    body: list[Block] = Field(default_factory=list)
    slides: list[Slide] = Field(default_factory=list)
    slide_size: tuple[float, float] | None = None
    warnings: list[str] = Field(default_factory=list)  # import limitations, stated honestly

    # --- convenience -------------------------------------------------------------------
    def headings(self) -> list[Heading]:
        return [b for b in self.body if isinstance(b, Heading)]

    def text_nodes(self) -> list[Paragraph | Heading | Caption]:
        return [b for b in self.body if isinstance(b, Paragraph | Heading | Caption)]

    def node(self, node_id: str) -> Block | None:
        return next((b for b in self.body if b.id == node_id), None)

    def plain_text(self) -> str:
        if self.slides:
            return "\n".join(s.text for sl in self.slides for s in sl.shapes)
        return "\n".join(b.text for b in self.body)
