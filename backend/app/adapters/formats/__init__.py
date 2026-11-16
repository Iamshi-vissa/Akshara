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


def apply_changes(path: Path, kind: str, adm: AdmDocument, ops: list) -> bytes:  # type: ignore[type-arg]
    """Patch the original file with accepted operations (DOCX/PPTX). PDFs are report-only (D5)."""
    from app.adapters.formats.docx_patcher import PatchError

    if kind == "docx":
        from app.adapters.formats.docx_patcher import apply_docx

        return apply_docx(path, adm, ops)
    if kind == "pptx":
        from app.adapters.formats.pptx_patcher import apply_pptx

        return apply_pptx(path, adm, ops)
    raise PatchError("PDF files cannot be corrected in place; corrections are reported only.")
