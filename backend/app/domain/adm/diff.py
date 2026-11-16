"""Structural diff between two ADM versions (by stable node id and text)."""

from __future__ import annotations

import difflib
from typing import Any

from app.domain.adm.model import AdmDocument


def _nodes(adm: AdmDocument) -> list[tuple[str, str, str, dict[str, Any]]]:
    out: list[tuple[str, str, str, dict[str, Any]]] = []
    for b in adm.body:
        fmt: dict[str, Any] = {}
        if hasattr(b, "dominant_run_fmt"):
            f = b.dominant_run_fmt()
            fmt = {"font": f.font_family, "size": f.size_pt, "spacing": b.fmt.line_spacing, "align": b.fmt.alignment}  # type: ignore[union-attr]
            if b.type == "heading":
                fmt["level"] = b.level
        out.append((b.id, b.type, b.text.strip(), fmt))
    for s in adm.slides:
        for sh in s.shapes:
            for p in sh.paragraphs:
                f = p.dominant_run_fmt()
                out.append((p.id, "paragraph", p.text.strip(), {"size": f.size_pt}))
    return out


def diff(a: AdmDocument, b: AdmDocument) -> dict[str, Any]:
    """Changes needed to turn ``a`` into ``b``: text/format edits, added and removed blocks, page setup."""
    na, nb = _nodes(a), _nodes(b)
    keys_a = [f"{t}:{x}" for _, t, x, _ in na]
    keys_b = [f"{t}:{x}" for _, t, x, _ in nb]
    changes: list[dict[str, Any]] = []
    sm = difflib.SequenceMatcher(a=keys_a, b=keys_b, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for i, j in zip(range(i1, i2), range(j1, j2), strict=True):
                if na[i][3] != nb[j][3]:
                    changed = {
                        k: [na[i][3].get(k), nb[j][3].get(k)] for k in nb[j][3] if na[i][3].get(k) != nb[j][3].get(k)
                    }
                    changes.append(
                        {"type": "format", "node_type": nb[j][1], "text": nb[j][2][:120], "changed": changed}
                    )
        elif tag == "replace" and (i2 - i1) == (j2 - j1):
            for i, j in zip(range(i1, i2), range(j1, j2), strict=True):
                changes.append({"type": "text", "node_type": nb[j][1], "before": na[i][2], "after": nb[j][2]})
        else:
            changes += [{"type": "removed", "node_type": na[i][1], "text": na[i][2][:200]} for i in range(i1, i2)]
            changes += [{"type": "added", "node_type": nb[j][1], "text": nb[j][2][:200]} for j in range(j1, j2)]
    setup: list[dict[str, Any]] = []
    for pa, pb in zip(a.page_setups, b.page_setups, strict=False):
        da, db = (
            pa.model_dump(exclude={"id", "headers", "footers", "first_page", "last_page"}),
            pb.model_dump(exclude={"id", "headers", "footers", "first_page", "last_page"}),
        )
        if da != db:
            setup.append({"section": pa.id, "before": da, "after": db})
        hfa = [h.has_page_number for h in [*pa.headers, *pa.footers]]
        hfb = [h.has_page_number for h in [*pb.headers, *pb.footers]]
        if any(hfb) != any(hfa):
            setup.append({"section": pa.id, "page_numbers": [any(hfa), any(hfb)]})
    counts = {k: sum(1 for c in changes if c["type"] == k) for k in ("text", "format", "added", "removed")}
    return {"counts": counts, "changes": changes[:500], "page_setup": setup}
