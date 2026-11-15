"""Phase 3 acceptance: planted defects are found, clean documents stay clean."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.adapters.formats import import_document
from app.adapters.render import render_document
from app.domain.adm.model import AdmDocument, Heading, Run, Source
from app.domain.inspection import InspectContext, inspect
from app.domain.scoring import Scored, score
from tests.fixtures.builders import KNOWN_DEFECTS

# Checks that need exact formatting cannot run on PDFs, which carry only inferred structure.
DOCX_ONLY = {"FMT.SPACING_INCONSISTENT", "LAYOUT.EMPTY_PARAGRAPHS", "PAGE.MARGINS_INCONSISTENT"}


def run(path: Path, kind: str):
    adm = import_document(path, kind)
    r = render_document(path, kind)
    layout = {"pages": [{"index": p.index, "spans": p.spans, "images": p.images} for p in r.pages]}
    return inspect(InspectContext(adm=adm, layout=layout))


@pytest.fixture(scope="module")
def results(fixture_docs):
    return {
        k: run(fixture_docs[k], k.split("_")[1])
        for k in ("clean_docx", "defective_docx", "clean_pdf", "defective_pdf", "clean_pptx", "overflow_pptx")
    }


def codes(result, min_severity=("critical", "high", "medium", "low")):
    return {f.code for f in result.findings if f.severity in min_severity}


def test_defective_docx_finds_exactly_the_planted_defects(results) -> None:
    assert codes(results["defective_docx"]) == KNOWN_DEFECTS


def test_defective_pdf_finds_the_planted_defects_that_pdf_can_show(results) -> None:
    assert codes(results["defective_pdf"]) == KNOWN_DEFECTS - DOCX_ONLY
    assert all(f.confidence < 1 for f in results["defective_pdf"].findings)  # inferred structure


@pytest.mark.parametrize("key", ["clean_docx", "clean_pdf", "clean_pptx"])
def test_clean_documents_have_nothing_above_low(results, key) -> None:
    serious = [f for f in results[key].findings if f.severity in ("critical", "high", "medium")]
    assert serious == [], [(f.code, f.message) for f in serious]


def test_overflow_deck(results) -> None:
    assert {"SLIDE.OFF_SLIDE", "SLIDE.TOO_MUCH_TEXT", "SLIDE.FONT_TOO_SMALL"} <= codes(results["overflow_pptx"])


def test_every_finding_is_actionable_and_located(results) -> None:
    for f in results["defective_docx"].findings:
        assert f.message and f.explanation and f.recommendation
        assert f.location
    skip = next(f for f in results["defective_docx"].findings if f.code == "STRUCT.HEADING_LEVEL_SKIP")
    assert skip.page == 0 and skip.bbox is not None  # mapped onto the rendered page


def test_not_evaluated_is_reported_not_passed() -> None:
    tiny = AdmDocument(
        source_format="docx", body=[Heading(id="h", source=Source(fmt="docx"), level=1, runs=[Run(text="Hi")])]
    )
    result = inspect(InspectContext(adm=tiny))
    assert {x["check"] for x in result.not_evaluated} >= {"FMT.FONT_INCONSISTENT", "FMT.SPACING_INCONSISTENT"}


def test_scoring() -> None:
    s = score([Scored("structure", "high"), Scored("typography", "medium"), Scored("typography", "low", 0.5)])
    assert s["dimensions"] == {"structure": 90.0, "formatting": 95.5, "references": 100.0, "visual": 100.0}
    assert s["overall"] == 96.4
    assert score([])["overall"] == 100.0
