"""Importer behaviour on the generated fixtures (no database needed)."""

from __future__ import annotations

from pathlib import Path

from app.adapters.formats import import_document
from app.domain.adm.model import AdmDocument, Caption, Figure, Heading, Table
from app.domain.adm.outline import outline, section_role, strip_numbering


def test_docx_effective_formatting_and_structure(fixture_docs: dict[str, Path]) -> None:
    adm = import_document(fixture_docs["defective_docx"], "docx")
    heads = adm.headings()
    assert [h.level for h in heads[:4]] == [0, 1, 3, 1]
    methods = next(h for h in heads if h.text == "2. Methods")
    assert methods.dominant_run_fmt().font_family == "Arial"  # direct formatting wins
    assert methods.dominant_run_fmt().size_pt == 16
    assert [ps.margins.left for ps in adm.page_setups if ps.margins] == [36.0, 72.0]
    figs = [b for b in adm.body if isinstance(b, Figure)]
    assert len(figs) == 3 and sum(f.caption_id is None for f in figs) == 1
    caps = [b for b in adm.body if isinstance(b, Caption)]
    assert [(c.label, c.number) for c in caps] == [("Figure", "1"), ("Figure", "3"), ("Table", "1")]
    tbl = next(b for b in adm.body if isinstance(b, Table))
    assert tbl.caption_id == caps[2].id


def test_adm_round_trips_through_json(fixture_docs: dict[str, Path]) -> None:
    for key, kind in [("clean_docx", "docx"), ("clean_pdf", "pdf"), ("clean_pptx", "pptx")]:
        adm = import_document(fixture_docs[key], kind)
        again = AdmDocument.model_validate_json(adm.model_dump_json())
        assert again == adm


def test_section_roles() -> None:
    assert section_role("1. Introduction") == "introduction"
    assert section_role("III. METHODOLOGY") == "methodology"
    assert section_role("Works Cited") == "references"
    assert section_role("Appendix A: Data") == "appendix"
    assert section_role("Our Fancy Idea") == "unknown"
    assert strip_numbering("2.1 Data Collection") == "Data Collection"


def test_pdf_outline_matches_docx(fixture_docs: dict[str, Path]) -> None:
    docx = import_document(fixture_docs["clean_docx"], "docx")
    pdf = import_document(fixture_docs["clean_pdf"], "pdf")

    def flat(nodes):  # type: ignore[no-untyped-def]
        return [(n.text, n.level) for n in nodes] + [x for n in nodes for x in flat(n.children)]

    assert flat(outline(pdf)) == flat(outline(docx))
    assert all(h.fidelity == "inferred" for h in pdf.headings())
    assert isinstance(docx.headings()[0], Heading)
