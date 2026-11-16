"""Property access and unit normalisation for UDSE selectors."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.domain.adm.model import AdmDocument, Caption, Figure, Heading, PageSetup, Paragraph, Shape, Slide, Table
from app.domain.adm.outline import count_words, section_role

TO_PT = {"pt": 1.0, "in": 72.0, "mm": 72.0 / 25.4, "cm": 72.0 / 2.54}
LENGTH_PROPS = {
    "margins.top",
    "margins.bottom",
    "margins.left",
    "margins.right",
    "width_pt",
    "height_pt",
    "size_pt",
    "space_before_pt",
    "space_after_pt",
    "indent_first_pt",
    "indent_left_pt",
    "line_spacing_pt",
}


def to_pt(v: Any, unit: str) -> Any:
    if unit in TO_PT and isinstance(v, int | float):
        return v * TO_PT[unit]
    return v


@dataclass
class Item:
    """One selected thing the rule applies to."""

    id: str | None
    props: dict[str, Any]
    fidelity: str  # exact | inferred | unknown
    text: str = ""
    page: int | None = None


def _text_props(n: Paragraph | Heading | Caption) -> dict[str, Any]:
    f = n.dominant_run_fmt()
    return {
        "font_family": f.font_family,
        "size_pt": f.size_pt,
        "bold": f.bold,
        "italic": f.italic,
        "alignment": n.fmt.alignment,
        "line_spacing": n.fmt.line_spacing,
        "line_spacing_pt": n.fmt.line_spacing_pt,
        "space_before_pt": n.fmt.space_before_pt,
        "space_after_pt": n.fmt.space_after_pt,
        "indent_first_pt": n.fmt.indent_first_pt,
        "indent_left_pt": n.fmt.indent_left_pt,
        "text": n.text.strip(),
        "style": n.style_ref,
    }


def _sections(adm: AdmDocument) -> list[tuple[Heading, list[Any]]]:
    """Each heading with its content: everything until the next heading of the same or a higher level."""
    body = adm.body
    out: list[tuple[Heading, list[Any]]] = []
    for i, b in enumerate(body):
        if not isinstance(b, Heading):
            continue
        content = []
        for x in body[i + 1 :]:
            if isinstance(x, Heading) and x.level <= b.level:
                break
            content.append(x)
        out.append((b, content))
    return out


def select(adm: AdmDocument, node: str, where: dict[str, Any]) -> list[Item]:
    fid = "exact" if adm.source_format != "pdf" else "inferred"
    items: list[Item] = []
    if node == "document":
        roles = sorted({section_role(h.text) for h in adm.headings()} - {"unknown"})
        has_num = any(hf.has_page_number for s in adm.page_setups for hf in [*s.headers, *s.footers])
        items.append(
            Item(
                id=None,
                fidelity=fid,
                props={
                    "word_count": adm.metadata.word_count,
                    "page_count": adm.metadata.page_count,
                    "has_page_numbers": has_num,
                    "section_roles": roles,
                    "columns": max((s.columns or 1 for s in adm.page_setups), default=None),
                    "title": adm.metadata.title,
                    "heading_count": len(adm.headings()),
                },
            )
        )
    elif node == "page_setup":
        for ps in adm.page_setups:
            items.append(Item(id=ps.id, fidelity=ps.fidelity, props=_setup_props(ps)))
    elif node in ("body_paragraph", "paragraph", "reference_entry"):
        for b in adm.body:
            if not isinstance(b, Paragraph):
                continue
            if node == "body_paragraph" and (b.role != "body" or len(b.text.strip()) < 20):
                continue
            if node == "reference_entry" and b.role != "reference_entry":
                continue
            if node == "paragraph" and b.role == "empty":
                continue
            items.append(
                Item(
                    id=b.id,
                    fidelity=b.fidelity,
                    props={**_text_props(b), "role": b.role},
                    text=b.text,
                    page=b.source.page,
                )
            )
    elif node == "heading":
        for h in adm.headings():
            items.append(
                Item(
                    id=h.id,
                    fidelity=h.fidelity,
                    text=h.text,
                    page=h.source.page,
                    props={
                        **_text_props(h),
                        "level": h.level,
                        "numbering_label": h.numbering_label,
                        "role": section_role(h.text),
                        "auto_numbered": h.auto_numbered,
                    },
                )
            )
    elif node == "caption":
        for c in (b for b in adm.body if isinstance(b, Caption)):
            items.append(
                Item(
                    id=c.id,
                    fidelity=c.fidelity,
                    text=c.text,
                    page=c.source.page,
                    props={
                        **_text_props(c),
                        "target_kind": c.target_kind,
                        "label": c.label,
                        "number": c.number,
                        "position": c.position,
                    },
                )
            )
    elif node == "figure":
        for f in (b for b in adm.body if isinstance(b, Figure)):
            items.append(
                Item(
                    id=f.id,
                    fidelity="exact" if fid == "exact" else "inferred",
                    page=f.source.page,
                    props={"has_caption": f.caption_id is not None, "alt_text": f.alt_text, "width_pt": f.width_pt},
                )
            )
    elif node == "table":
        for t in (b for b in adm.body if isinstance(b, Table)):
            items.append(
                Item(
                    id=t.id,
                    fidelity=fid,
                    page=t.source.page,
                    props={"has_caption": t.caption_id is not None, "width_pt": t.width_pt},
                )
            )
    elif node == "section":
        for h, blocks in _sections(adm):
            text = " ".join(getattr(b, "text", "") for b in blocks)
            items.append(
                Item(
                    id=h.id,
                    fidelity=h.fidelity,
                    text=text,
                    page=h.source.page,
                    props={
                        "role": section_role(h.text),
                        "title": h.text.strip(),
                        "word_count": count_words(text),
                        "level": h.level,
                    },
                )
            )
    elif node == "slide":
        for sl in adm.slides:
            items.append(
                Item(
                    id=sl.id,
                    fidelity="exact",
                    page=sl.index,
                    text=" ".join(sh.text for sh in sl.shapes),
                    props=_slide_props(sl),
                )
            )
    elif node == "shape":
        for sl in adm.slides:
            for sh in sl.shapes:
                items.append(Item(id=sh.id, fidelity="exact", page=sl.index, text=sh.text, props=_shape_props(sh)))
    return [i for i in items if _matches(i.props, where)]


def _setup_props(s: PageSetup) -> dict[str, Any]:
    m = s.margins
    return {
        "paper": s.paper,
        "orientation": s.orientation,
        "width_pt": s.width_pt,
        "height_pt": s.height_pt,
        "columns": s.columns,
        "margins.top": m.top if m else None,
        "margins.bottom": m.bottom if m else None,
        "margins.left": m.left if m else None,
        "margins.right": m.right if m else None,
        "has_page_numbers": any(hf.has_page_number for hf in [*s.headers, *s.footers]),
    }


def _slide_props(s: Slide) -> dict[str, Any]:
    sizes = [r.fmt.size_pt for sh in s.shapes for p in sh.paragraphs for r in p.runs if r.fmt.size_pt]
    return {
        "title": s.title,
        "word_count": sum(count_words(sh.text) for sh in s.shapes),
        "has_notes": bool(s.notes.strip()),
        "min_font_pt": min(sizes) if sizes else None,
    }


def _shape_props(sh: Shape) -> dict[str, Any]:
    fonts = {r.fmt.font_family for p in sh.paragraphs for r in p.runs if r.fmt.font_family}
    sizes = [r.fmt.size_pt for p in sh.paragraphs for r in p.runs if r.fmt.size_pt]
    return {
        "kind": sh.kind,
        "placeholder": sh.placeholder,
        "font_family": next(iter(fonts)) if len(fonts) == 1 else None,
        "min_font_pt": min(sizes) if sizes else None,
    }


def _matches(props: dict[str, Any], where: dict[str, Any]) -> bool:
    for k, v in where.items():
        actual = props.get(k)
        if isinstance(v, list):
            if actual not in v:
                return False
        elif isinstance(v, str) and isinstance(actual, str):
            if actual.lower() != v.lower():
                return False
        elif actual != v:
            return False
    return True


def norm_text(v: Any) -> Any:
    return re.sub(r"\s+", " ", v).strip().lower() if isinstance(v, str) else v
