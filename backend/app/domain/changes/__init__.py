"""Change operations: the only way a document is modified (ARCHITECTURE.md §7.6).

Every AI edit, grammar fix, automatic correction and manual edit becomes a list of these
operations inside a change proposal. Nothing is applied until a person accepts it.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Risk = Literal["formatting_only", "structural", "content_change"]


class _Op(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SetPageSetup(_Op):
    op: Literal["set_page_setup"] = "set_page_setup"
    page_setup_ids: list[str] | Literal["all"] = "all"
    margins_pt: dict[str, float] | None = None  # any of top/bottom/left/right
    paper: Literal["Letter", "A4"] | None = None
    columns: int | None = Field(default=None, ge=1, le=4)


class SetParaFmt(_Op):
    op: Literal["set_para_fmt"] = "set_para_fmt"
    node_ids: list[str]
    line_spacing: float | None = Field(default=None, gt=0, le=4)
    alignment: Literal["left", "center", "right", "justify"] | None = None
    space_before_pt: float | None = None
    space_after_pt: float | None = None
    indent_first_pt: float | None = None


class SetRunFmt(_Op):
    op: Literal["set_run_fmt"] = "set_run_fmt"
    node_ids: list[str]
    font_family: str | None = None
    size_pt: float | None = Field(default=None, gt=1, le=200)
    bold: bool | None = None


class SetHeadingLevel(_Op):
    op: Literal["set_heading_level"] = "set_heading_level"
    node_id: str
    level: int = Field(ge=1, le=9)


class ReplaceText(_Op):
    op: Literal["replace_text"] = "replace_text"
    node_id: str
    before: str  # guard: the paragraph must still read exactly this
    after: str


class DeleteBlocks(_Op):
    op: Literal["delete_blocks"] = "delete_blocks"
    node_ids: list[str]


class AddPageNumbers(_Op):
    op: Literal["add_page_numbers"] = "add_page_numbers"
    position: Literal["header-right", "footer-center", "footer-right"] = "footer-center"


class SortReferences(_Op):
    op: Literal["sort_references"] = "sort_references"
    node_ids: list[str]
    order: Literal["alphabetical", "numeric"]


class FitShape(_Op):
    op: Literal["fit_shape"] = "fit_shape"  # PPTX: move/resize a shape inside the slide
    node_id: str
    bbox_pt: tuple[float, float, float, float]


class SetShapeFontMin(_Op):
    op: Literal["set_shape_font_min"] = "set_shape_font_min"  # PPTX: raise small text
    node_id: str
    min_pt: float = Field(gt=4, le=96)


Operation = Annotated[
    SetPageSetup
    | SetParaFmt
    | SetRunFmt
    | SetHeadingLevel
    | ReplaceText
    | DeleteBlocks
    | AddPageNumbers
    | SortReferences
    | FitShape
    | SetShapeFontMin,
    Field(discriminator="op"),
]

DOCX_OPS = {
    "set_page_setup",
    "set_para_fmt",
    "set_run_fmt",
    "set_heading_level",
    "replace_text",
    "delete_blocks",
    "add_page_numbers",
    "sort_references",
}
PPTX_OPS = {"fit_shape", "set_shape_font_min", "replace_text"}


class Proposal(BaseModel):
    """A suggested change, with everything a reviewer needs to decide."""

    title: str
    rationale: str
    ops: list[Operation]
    risk: Risk
    before: str = ""
    after: str = ""
    finding_codes: list[str] = Field(default_factory=list)
    rule_id: str | None = None
    node_ids: list[str] = Field(default_factory=list)
