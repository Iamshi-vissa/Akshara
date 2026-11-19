"""Document rendering: DOCX/PPTX → PDF (LibreOffice headless) → page PNGs + layout (PyMuPDF).

Safety (ARCHITECTURE.md §10 R5/R6): LibreOffice runs as a subprocess with a throw-away
profile, a hard timeout, macros disabled by default in headless mode, and its process group
killed on timeout. The input was already validated by the upload gate (no macro packages).
Rendering differs slightly from Microsoft Office (fonts, line breaking); layout findings carry
that caveat.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pymupdf

RENDER_TIMEOUT_S = 180
PREVIEW_DPI = 110
MAX_RENDER_PAGES = 300


class RenderUnavailable(Exception):
    """The renderer cannot run here (e.g. LibreOffice is not installed)."""


@dataclass
class RenderedPage:
    index: int
    width_pt: float
    height_pt: float
    png: bytes
    blank: bool
    spans: list[dict[str, Any]] = field(default_factory=list)
    images: list[tuple[float, float, float, float]] = field(default_factory=list)
    drawings_bbox: tuple[float, float, float, float] | None = None
    drawings: list[tuple[float, float, float, float]] = field(default_factory=list)


@dataclass
class RenderResult:
    pdf: bytes
    pages: list[RenderedPage]
    page_count: int
    truncated: bool
    renderer: str


def soffice_path() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice")


def convert_to_pdf(src: Path, timeout: int = RENDER_TIMEOUT_S) -> bytes:
    exe = soffice_path()
    if exe is None:
        raise RenderUnavailable("LibreOffice is not installed; pages cannot be rendered.")
    with tempfile.TemporaryDirectory(prefix="akshara-render-") as tmp:
        tmpdir = Path(tmp)
        profile = tmpdir / "profile"
        outdir = tmpdir / "out"
        outdir.mkdir()
        # Copy under a neutral name: the original filename never reaches the command line.
        work = tmpdir / f"input{src.suffix.lower()}"
        shutil.copyfile(src, work)
        cmd = [
            exe,
            "--headless",
            "--norestore",
            "--nolockcheck",
            "--nodefault",
            f"-env:UserInstallation=file://{profile}",
            "--convert-to",
            "pdf",
            "--outdir",
            str(outdir),
            str(work),
        ]
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(tmpdir),
            "LANG": "C.UTF-8",
        }
        proc = subprocess.Popen(  # noqa: S603 fixed argv, no shell
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=env, start_new_session=True
        )
        try:
            proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            raise RuntimeError("Rendering timed out.") from None
        out = outdir / "input.pdf"
        if proc.returncode != 0 or not out.exists():
            raise RuntimeError(f"LibreOffice could not render the document ({proc.returncode}).")
        return out.read_bytes()


def _is_blank(pix: pymupdf.Pixmap) -> bool:
    """A page is blank when (almost) every sampled pixel is near-white."""
    samples = pix.samples
    n = pix.n
    step = max(1, (len(samples) // n) // 4000) * n
    dark = 0
    total = 0
    for i in range(0, len(samples) - n + 1, step):
        total += 1
        if min(samples[i : i + min(3, n)]) < 235:
            dark += 1
    return total > 0 and dark / total < 0.0008


def _background(pix: pymupdf.Pixmap, bbox: list[float], scale: float) -> int | None:
    """Most common (quantised) colour inside a text box — the background the text sits on.

    Glyph pixels are a minority of a span's box, so the mode is the background. Sampled on a
    coarse grid to keep rendering fast.
    """
    x0, y0, x1, y1 = (int(v * scale) for v in bbox)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(pix.width - 1, x1), min(pix.height - 1, y1)
    if x1 <= x0 or y1 <= y0:
        return None
    n, stride, samples = pix.n, pix.stride, pix.samples
    counts: dict[int, int] = {}
    step_x = max(1, (x1 - x0) // 24)
    step_y = max(1, (y1 - y0) // 6)
    for y in range(y0, y1 + 1, step_y):
        row = y * stride
        for x in range(x0, x1 + 1, step_x):
            o = row + x * n
            r, g, b = samples[o], samples[o + 1], samples[o + 2]
            key = ((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4)
            counts[key] = counts.get(key, 0) + 1
    if not counts:
        return None
    q = max(counts, key=lambda k: counts[k])
    # back to 0xRRGGBB using the centre of each 16-level bucket
    return (((q >> 8) * 17) << 16) | ((((q >> 4) & 15) * 17) << 8) | ((q & 15) * 17)


def rasterize(
    pdf_bytes: bytes, dpi: int = PREVIEW_DPI, max_pages: int = MAX_RENDER_PAGES
) -> tuple[list[RenderedPage], int]:
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        pages: list[RenderedPage] = []
        for pno in range(min(doc.page_count, max_pages)):
            page = doc[pno]
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            scale = dpi / 72.0
            spans = []
            for b in page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]:
                for line in b.get("lines", []):
                    for s in line["spans"]:
                        if s["text"].strip():
                            spans.append(
                                {
                                    "text": s["text"],
                                    "bbox": [round(v, 2) for v in s["bbox"]],
                                    "size": round(s["size"], 1),
                                    "font": s["font"],
                                    "color": s.get("color", 0),
                                    "bg": _background(pix, s["bbox"], scale),
                                }
                            )
            images = [tuple(round(v, 2) for v in i["bbox"]) for i in page.get_image_info()]
            rect = None
            draws = page.get_drawings()
            drawn: list[tuple[float, float, float, float]] = []
            if draws:
                r = pymupdf.Rect()
                for d in draws:
                    r |= d["rect"]
                    dr = d["rect"]
                    # keep visible shapes (table rules, boxes); skip specks and full-page backgrounds
                    if (dr.width > 4 or dr.height > 4) and len(drawn) < 400:
                        drawn.append((round(dr.x0, 2), round(dr.y0, 2), round(dr.x1, 2), round(dr.y1, 2)))
                rect = (round(r.x0, 2), round(r.y0, 2), round(r.x1, 2), round(r.y1, 2))
            pages.append(
                RenderedPage(
                    index=pno,
                    width_pt=round(page.rect.width, 2),
                    height_pt=round(page.rect.height, 2),
                    png=pix.tobytes("png"),
                    blank=_is_blank(pix) and not spans and not images,
                    spans=spans,
                    images=images,
                    drawings_bbox=rect,
                    drawings=drawn,
                )
            )
        return pages, doc.page_count
    finally:
        doc.close()


def render_document(path: Path, kind: str) -> RenderResult:
    pdf = path.read_bytes() if kind == "pdf" else convert_to_pdf(path)
    pages, count = rasterize(pdf)
    return RenderResult(
        pdf=pdf,
        pages=pages,
        page_count=count,
        truncated=count > len(pages),
        renderer="pymupdf" if kind == "pdf" else "libreoffice+pymupdf",
    )
