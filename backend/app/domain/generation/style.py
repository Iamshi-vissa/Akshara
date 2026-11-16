"""Derive page and typography settings for a generated document from a standard's rules."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.udse.properties import to_pt
from app.domain.udse.schema import StandardProfile


@dataclass
class StyleSpec:
    paper: str = "Letter"
    margins_pt: tuple[float, float, float, float] = (72.0, 72.0, 72.0, 72.0)  # top, bottom, left, right
    font: str = "Calibri"
    size_pt: float = 11.0
    line_spacing: float = 1.15
    alignment: str = "left"
    columns: int = 1
    page_numbers: str = "footer-center"
    references_title: str = "References"


def from_profile(profile: StandardProfile | None) -> StyleSpec:
    spec = StyleSpec()
    if profile is None:
        return spec
    margins = list(spec.margins_pt)
    sides = {"margins.top": 0, "margins.bottom": 1, "margins.left": 2, "margins.right": 3}
    for r in profile.rules:
        c = r.check
        if not r.enabled:
            continue
        val = c.value if c.value is not None else (c.values[0] if c.values else None)
        if c.property in sides and c.op == "equals" and isinstance(val, int | float):
            margins[sides[c.property]] = round(to_pt(val, c.unit), 2)
        elif c.property == "paper" and val in ("Letter", "A4"):
            spec.paper = val
        elif c.property == "font_family" and isinstance(val, str):
            spec.font = val
        elif c.property == "size_pt":
            if isinstance(c.value, int | float):
                spec.size_pt = float(c.value)
            elif c.max is not None:
                spec.size_pt = float(c.max)
        elif c.property == "line_spacing" and isinstance(val, int | float):
            spec.line_spacing = float(val)
        elif c.property == "alignment" and val in ("left", "justify", "center", "right"):
            spec.alignment = val
        elif c.property == "columns" and isinstance(val, int):
            spec.columns = val
        elif c.property == "text" and c.pattern and r.selector.where.get("role") == "references":
            spec.references_title = c.pattern.strip("^$").replace("\\", "").title()
    spec.margins_pt = (margins[0], margins[1], margins[2], margins[3])
    if profile.family in ("apa", "mla"):
        spec.page_numbers = "header-right"
    return spec
