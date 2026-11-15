"""Format adapters: importers (file → ADM), exporters (ADM → file), patchers (file + ops)."""

from __future__ import annotations

from pathlib import Path

from app.domain.adm.model import AdmDocument


def import_document(path: Path, kind: str) -> AdmDocument:
    if kind == "docx":
        from app.adapters.formats.docx_importer import import_docx

        return import_docx(path)
    if kind == "pdf":
        from app.adapters.formats.pdf_importer import import_pdf

        return import_pdf(path)
    if kind == "pptx":
        from app.adapters.formats.pptx_importer import import_pptx

        return import_pptx(path)
    raise ValueError(f"unsupported kind: {kind}")
