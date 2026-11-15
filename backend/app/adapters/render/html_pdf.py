"""Render a self-contained HTML report to PDF with PyMuPDF's Story engine (no browser)."""

from __future__ import annotations

import io

import pymupdf


def html_to_pdf(html: str, paper: str = "a4") -> bytes:
    story = pymupdf.Story(html=html)
    buf = io.BytesIO()
    writer = pymupdf.DocumentWriter(buf)
    mediabox = pymupdf.paper_rect(paper)
    where = pymupdf.Rect(mediabox.x0 + 48, mediabox.y0 + 48, mediabox.x1 - 48, mediabox.y1 - 48)
    more = True
    while more:
        device = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()
    writer.close()
    return buf.getvalue()
