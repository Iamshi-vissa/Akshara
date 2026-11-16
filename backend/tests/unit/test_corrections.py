"""Phase 5: planned corrections fix what they target, break nothing, and never touch the original."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.adapters.formats import apply_changes, import_document
from app.adapters.formats.docx_patcher import PatchError
from app.adapters.languagetool import GrammarMatch, apply_matches
from app.domain.changes import ReplaceText
from app.domain.correction import FindingRef, plan, to_roman
from app.domain.inspection import InspectContext, inspect
from app.domain.udse.engine import evaluate
from app.standards import builtin_profiles

FIXABLE = {
    "STRUCT.HEADING_LEVEL_SKIP",
    "FIG.NUMBERING",
    "FMT.FONT_INCONSISTENT",
    "FMT.HEADING_INCONSISTENT",
    "PAGE.NO_PAGE_NUMBERS",
    "PAGE.MARGINS_INCONSISTENT",
    "FMT.SPACING_INCONSISTENT",
    "LAYOUT.EMPTY_PARAGRAPHS",
    "REF.ORDER",
}


def refs(findings):
    return [
        FindingRef(id=str(i), code=f.code, node_ids=f.node_ids, expected=f.expected, actual=f.actual, rule_id=f.rule_id)
        for i, f in enumerate(findings)
    ]


def test_apply_all_inspection_fixes(fixture_docs, tmp_path: Path) -> None:
    src = fixture_docs["defective_docx"]
    digest = hashlib.sha256(src.read_bytes()).hexdigest()
    adm = import_document(src, "docx")
    before = inspect(InspectContext(adm=adm))
    planned = plan(adm, refs(before.findings))
    out = tmp_path / "fixed.docx"
    out.write_bytes(apply_changes(src, "docx", adm, [o for p in planned for o in p.proposal.ops]))
    after = inspect(InspectContext(adm=import_document(out, "docx")))
    codes_before, codes_after = {f.code for f in before.findings}, {f.code for f in after.findings}
    assert FIXABLE <= codes_before
    assert not (FIXABLE & codes_after), FIXABLE & codes_after
    assert codes_after <= codes_before  # nothing new introduced
    assert hashlib.sha256(src.read_bytes()).hexdigest() == digest  # original untouched


def test_renumbering_updates_in_text_references(fixture_docs, tmp_path: Path) -> None:
    src = fixture_docs["defective_docx"]
    adm = import_document(src, "docx")
    planned = plan(adm, refs([f for f in inspect(InspectContext(adm=adm)).findings if f.code == "FIG.NUMBERING"]))
    out = tmp_path / "renum.docx"
    out.write_bytes(apply_changes(src, "docx", adm, [o for p in planned for o in p.proposal.ops]))
    text = import_document(out, "docx").plain_text()
    assert "Figure 2. Third result." in text and "Figure 1 and Figure 2 show" in text and "Figure 3" not in text


def test_apa_rule_fixes_bring_margins_and_spacing_into_compliance(fixture_docs, tmp_path: Path) -> None:
    src = fixture_docs["defective_docx"]
    adm = import_document(src, "docx")
    apa = builtin_profiles()["apa-7"]
    result = evaluate(apa, adm)
    planned = plan(adm, refs(result.findings), {r.id: r for r in apa.rules}, "apa")
    out = tmp_path / "apa.docx"
    out.write_bytes(apply_changes(src, "docx", adm, [o for p in planned for o in p.proposal.ops]))
    again = evaluate(apa, import_document(out, "docx"))
    status = {r.rule.id: r.status for r in again.results}
    for rule in (
        "page.margin.left",
        "typography.double_spacing",
        "page.page_numbers",
        "references.alphabetical",
        "figures.numbering",
    ):
        assert status[rule] == "pass", rule
    assert again.compliance["score"] > result.compliance["score"]


def test_stale_text_guard(fixture_docs) -> None:
    src = fixture_docs["clean_docx"]
    adm = import_document(src, "docx")
    para = next(b for b in adm.body if b.type == "paragraph" and b.role == "body")
    with pytest.raises(PatchError, match="changed since"):
        apply_changes(src, "docx", adm, [ReplaceText(node_id=para.id, before="something else", after="x")])


def test_pdf_cannot_be_patched(fixture_docs) -> None:
    adm = import_document(fixture_docs["clean_pdf"], "pdf")
    with pytest.raises(PatchError, match="reported only"):
        apply_changes(fixture_docs["clean_pdf"], "pdf", adm, [])


def test_pptx_off_slide_and_small_font_fixes(fixture_docs, tmp_path: Path) -> None:
    src = fixture_docs["overflow_pptx"]
    adm = import_document(src, "pptx")
    found = [
        f for f in inspect(InspectContext(adm=adm)).findings if f.code in ("SLIDE.OFF_SLIDE", "SLIDE.FONT_TOO_SMALL")
    ]
    planned = plan(adm, refs(found))
    out = tmp_path / "deck.pptx"
    out.write_bytes(apply_changes(src, "pptx", adm, [o for p in planned for o in p.proposal.ops]))
    after = {f.code for f in inspect(InspectContext(adm=import_document(out, "pptx"))).findings}
    assert "SLIDE.OFF_SLIDE" not in after and "SLIDE.FONT_TOO_SMALL" not in after


def test_grammar_matches_apply_right_to_left_without_overlap() -> None:
    text = "This are a sentence with a error."
    ms = [
        GrammarMatch(0, 8, "m1", "These are", "r", "c"),
        GrammarMatch(5, 3, "m2", "is", "r", "c"),
        GrammarMatch(25, 1, "m3", "an", "r", "c"),
    ]
    new, used = apply_matches(text, ms)
    # m2 (applied first, right to left) overlaps m1, so m1 is skipped rather than corrupting the text.
    assert new == "This is a sentence with an error." and [m.message for m in used] == ["m2", "m3"]


def test_adjacent_alternative_grammar_fixes_are_not_combined() -> None:
    text = "This are a sentence."
    ms = [GrammarMatch(0, 4, "these", "These", "r", "GRAMMAR"), GrammarMatch(5, 3, "is", "is", "r", "GRAMMAR")]
    new, used = apply_matches(text, ms)
    assert new == "This is a sentence." and len(used) == 1


def test_roman() -> None:
    assert [to_roman(n) for n in (1, 4, 9, 14, 40)] == ["I", "IV", "IX", "XIV", "XL"]
