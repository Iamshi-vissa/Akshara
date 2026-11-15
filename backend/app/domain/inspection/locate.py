"""Map ADM nodes to rendered pages, so findings can be shown on the page image.

DOCX/PPTX have no page geometry in the file; we align node text with the text spans that the
renderer produced. This is approximate (ARCHITECTURE.md §10 R13): the confidence is reported
and a node that cannot be matched simply has no page.
"""

from __future__ import annotations

import re
from typing import Any

from app.domain.adm.model import AdmDocument, Figure, Table

_WS = re.compile(r"\s+")


def _norm(t: str) -> str:
    return _WS.sub(" ", t).strip().lower()


class Locator:
    def __init__(self, adm: AdmDocument, layout: dict[str, Any] | None) -> None:
        self.adm = adm
        self.pages: list[dict[str, Any]] = (layout or {}).get("pages", [])
        self._map: dict[str, tuple[int | None, tuple[float, float, float, float] | None]] = {}
        self._aligned = False

    def locate(self, node_id: str) -> tuple[int | None, tuple[float, float, float, float] | None]:
        if not self._aligned:
            self._align()
        if node_id in self._map:
            return self._map[node_id]
        m = re.match(r"^s(\d+)", node_id)  # slide ids: s3, s3.sh5
        if self.adm.slides and m:
            return int(m.group(1)), None
        return None, None

    def _align(self) -> None:
        """Walk body nodes and rendered spans together, in reading order."""
        self._aligned = True
        flat: list[tuple[int, int, dict[str, Any]]] = []  # (page, char offset, span)
        text_parts: list[str] = []
        offset = 0
        for p in self.pages:
            for s in p.get("spans", []):
                t = _norm(s["text"]) + " "
                flat.append((p["index"], offset, s))
                text_parts.append(t)
                offset += len(t)
        full = "".join(text_parts)
        images = [(p["index"], tuple(img)) for p in self.pages for img in p.get("images", [])]
        img_i = 0
        cursor = 0
        for node in self.adm.body:
            if node.source.page is not None:  # PDF: geometry is native
                self._map[node.id] = (node.source.page, node.source.bbox)
                continue
            if isinstance(node, Figure):
                if img_i < len(images):
                    page, bbox = images[img_i]
                    self._map[node.id] = (page, bbox)
                    img_i += 1
                continue
            if isinstance(node, Table):
                text = " ".join(c.text for row in node.rows[:1] for c in row)
            else:
                text = node.text
            needle = _norm(text)[:32]
            if len(needle) < 3:
                continue
            pos = full.find(needle, cursor)
            if pos < 0:
                continue
            end = pos + len(_norm(text))
            covered = [f for f in flat if f[1] + len(_norm(f[2]["text"])) >= pos and f[1] < end]
            if not covered:
                continue
            page = covered[0][0]
            same = [f[2]["bbox"] for f in covered if f[0] == page][:40]
            x0 = min(b[0] for b in same)
            y0 = min(b[1] for b in same)
            x1 = max(b[2] for b in same)
            y1 = max(b[3] for b in same)
            self._map[node.id] = (page, (x0, y0, x1, y1))
            cursor = pos + len(needle)

    def label(self, node_id: str, page: int | None) -> str:
        node = self.adm.node(node_id)
        if node is not None and node.type == "heading":
            where = f"heading “{node.text.strip()[:60]}”"
            return f"{where}, page {page + 1}" if page is not None else where
        section = None
        for b in self.adm.body:
            if b.id == node_id:
                break
            if b.type == "heading":
                section = b.text.strip()
        parts = []
        if section:
            parts.append(f"in “{section[:60]}”")
        if page is not None:
            parts.append(f"slide {page + 1}" if self.adm.slides else f"page {page + 1}")
        return ", ".join(parts)
