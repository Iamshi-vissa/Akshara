"""Apply change operations to an original PPTX (patch-based, like the DOCX patcher)."""

from __future__ import annotations

import io
import re
from pathlib import Path

from pptx import Presentation
from pptx.util import Pt

from app.domain.adm.model import AdmDocument
from app.domain.changes import FitShape, Operation, ReplaceText, SetShapeFontMin

from .docx_patcher import PatchError

SHAPE_ID = re.compile(r"^s(\d+)\.sh(\d+)")


def apply_pptx(src: Path, adm: AdmDocument, ops: list[Operation]) -> bytes:
    prs = Presentation(str(src))
    slides = list(prs.slides)

    def shape(node_id: str):  # type: ignore[no-untyped-def]
        m = SHAPE_ID.match(node_id)
        if not m or int(m.group(1)) >= len(slides):
            raise PatchError(f"Shape {node_id} not found.")
        for sh in slides[int(m.group(1))].shapes:
            if sh.shape_id == int(m.group(2)):
                return sh
        raise PatchError(f"Shape {node_id} not found.")

    for op in ops:
        if isinstance(op, FitShape):
            sh = shape(op.node_id)
            x0, y0, x1, y1 = op.bbox_pt
            sh.left, sh.top, sh.width, sh.height = Pt(x0), Pt(y0), Pt(x1 - x0), Pt(y1 - y0)
        elif isinstance(op, SetShapeFontMin):
            sh = shape(op.node_id)
            if not sh.has_text_frame:
                raise PatchError("The shape has no text.")
            for p in sh.text_frame.paragraphs:
                for r in p.runs:
                    if r.font.size is not None and r.font.size.pt < op.min_pt:
                        r.font.size = Pt(op.min_pt)
        elif isinstance(op, ReplaceText):
            m = re.match(r"^(s\d+\.sh\d+)\.p(\d+)$", op.node_id)
            if not m:
                raise PatchError(f"Paragraph {op.node_id} not found.")
            sh = shape(m.group(1))
            paras = sh.text_frame.paragraphs
            p = paras[int(m.group(2))] if int(m.group(2)) < len(paras) else None
            if p is None or "".join(r.text for r in p.runs).strip() != op.before.strip():
                raise PatchError("The slide text changed since this edit was proposed.")
            runs = p.runs
            runs[0].text = op.after
            for r in runs[1:]:
                r._r.getparent().remove(r._r)
        else:
            raise PatchError(f"Operation {op.op} is not supported for presentations.")
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()
