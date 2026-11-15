"""AKSHARA Document Model (ADM): the canonical, format-independent document representation.

Every importer produces an :class:`AdmDocument`; every inspection, validation, correction and
export module works on it. See docs/ARCHITECTURE.md §7.
"""

from app.domain.adm.model import (
    ADM_SCHEMA_VERSION,
    AdmDocument,
    Block,
    Caption,
    Figure,
    HeaderFooter,
    Heading,
    Mark,
    Metadata,
    PageBreak,
    PageSetup,
    ParaFmt,
    Paragraph,
    Run,
    RunFmt,
    Shape,
    Slide,
    Source,
    Table,
    TableCell,
)

__all__ = [
    "ADM_SCHEMA_VERSION",
    "AdmDocument",
    "Block",
    "Caption",
    "Figure",
    "HeaderFooter",
    "Heading",
    "Mark",
    "Metadata",
    "PageBreak",
    "PageSetup",
    "ParaFmt",
    "Paragraph",
    "Run",
    "RunFmt",
    "Shape",
    "Slide",
    "Source",
    "Table",
    "TableCell",
]
