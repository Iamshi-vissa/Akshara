"""Phase 4: deterministic UDSE rules, units, compliance cap, extraction grounding."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.adapters.formats import import_document
from app.domain.adm.model import AdmDocument, Margins, PageSetup, ParaFmt, Paragraph, Run, RunFmt, Source
from app.domain.udse.engine import HARD_CAP, evaluate
from app.domain.udse.extraction import Candidate, extract, verify_candidate
from app.domain.udse.schema import Rule, StandardProfile, merge
from app.standards import builtin_profiles


def doc(margin_left=72.0, size=12.0, spacing=2.0, fmt="docx", fidelity="exact") -> AdmDocument:
    body = [
        Paragraph(
            id=f"p{i}",
            source=Source(fmt=fmt),
            fidelity=fidelity,
            runs=[
                Run(
                    text="Body text long enough to count as running text.",
                    fmt=RunFmt(font_family="Times New Roman", size_pt=size),
                )
            ],
            fmt=ParaFmt(line_spacing=spacing, alignment="left"),
        )
        for i in range(3)
    ]
    ps = PageSetup(
        id="ps0",
        width_pt=612,
        height_pt=792,
        orientation="portrait",
        fidelity=fidelity,
        margins=Margins(top=72, bottom=72, left=margin_left, right=72),
    )
    return AdmDocument(source_format=fmt, page_setups=[ps], body=body)


def margin_rule(kind="hard", sev="high") -> dict:
    return {
        "id": "page.margin.left",
        "title": "Left margin",
        "category": "page",
        "kind": kind,
        "severity": sev,
        "selector": {"node": "page_setup"},
        "check": {"op": "equals", "property": "margins.left", "value": 1, "unit": "in", "tolerance": 0.05},
    }


def profile(*rules: dict) -> StandardProfile:
    return StandardProfile(slug="test", name="Test", family="custom", rules=[Rule.model_validate(r) for r in rules])


def test_units_and_tolerance() -> None:
    p = profile(margin_rule())
    assert evaluate(p, doc(72.0)).results[0].status == "pass"
    assert evaluate(p, doc(74.0)).results[0].status == "pass"  # within 0.05 in (3.6 pt)
    r = evaluate(p, doc(36.0)).results[0]
    assert r.status == "fail" and r.violations[0].actual == 36.0


def test_failure_message_uses_rule_units() -> None:
    f = evaluate(profile(margin_rule()), doc(36.0)).findings[0]
    assert f.message.startswith("Left margin: found 0.5 in, expected 1 in")
    assert f.constraint == "hard" and f.rule_id == "page.margin.left"


def test_inferred_pdf_margins_only_fail_when_text_intrudes() -> None:
    p = profile(margin_rule())
    assert evaluate(p, doc(90.0, fmt="pdf", fidelity="inferred")).results[0].status == "pass"
    assert evaluate(p, doc(40.0, fmt="pdf", fidelity="inferred")).results[0].status == "fail"


def test_hard_failure_caps_compliance() -> None:
    soft_ok = {
        "id": "t.size",
        "title": "Size",
        "category": "typography",
        "kind": "soft",
        "severity": "critical",
        "selector": {"node": "body_paragraph"},
        "check": {"op": "equals", "property": "size_pt", "value": 12, "unit": "pt"},
    }
    c = evaluate(profile(margin_rule(sev="low"), soft_ok), doc(36.0)).compliance
    assert c["raw_score"] > HARD_CAP and c["score"] == HARD_CAP and c["verdict"] == "not compliant" and c["cap_applied"]
    c2 = evaluate(profile(margin_rule(), soft_ok), doc(72.0)).compliance
    assert c2["score"] == 100.0 and c2["verdict"] == "compliant"


def test_unknown_values_are_not_evaluated_never_passed() -> None:
    spacing = {
        "id": "t.ls",
        "title": "Spacing",
        "category": "typography",
        "kind": "hard",
        "severity": "high",
        "selector": {"node": "body_paragraph"},
        "check": {"op": "equals", "property": "line_spacing", "value": 2.0},
    }
    r = evaluate(profile(spacing), doc(spacing=None)).results[0]  # type: ignore[arg-type]
    assert r.status == "not_evaluated" and "could not be determined" in r.reason
    assert evaluate(profile(spacing), doc(spacing=None)).compliance["verdict"] == "not evaluated"  # type: ignore[arg-type]


def test_llm_rules_must_be_soft_and_need_a_rubric() -> None:
    base = {
        "id": "t.llm",
        "title": "Clarity",
        "category": "structure",
        "severity": "low",
        "selector": {"node": "section"},
        "check": {"op": "llm_assess", "rubric": "States the problem."},
    }
    with pytest.raises(ValidationError):
        Rule.model_validate({**base, "kind": "hard"})
    with pytest.raises(ValidationError):
        Rule.model_validate({**base, "kind": "soft", "check": {"op": "llm_assess"}})
    r = evaluate(profile({**base, "kind": "soft"}), doc()).results[0]
    assert r.status == "not_evaluated" and "language model" in r.reason


def test_inheritance_overrides_by_id() -> None:
    apa = builtin_profiles()["apa-7"]
    child = StandardProfile(
        slug="uni",
        name="Uni",
        family="institutional",
        extends="apa-7",
        rules=[Rule.model_validate({**margin_rule(), "check": {**margin_rule()["check"], "value": 1.5}})],
    )
    merged = merge(apa, child)
    assert len(merged.rules) == len(apa.rules)
    assert next(r for r in merged.rules if r.id == "page.margin.left").check.value == 1.5


def test_builtins_cite_sources() -> None:
    for p in builtin_profiles().values():
        for r in p.rules:
            assert r.provenance and r.provenance.source and r.provenance.verification in ("secondary", "unverified")


def test_validation_is_deterministic(fixture_docs) -> None:
    adm = import_document(fixture_docs["defective_docx"], "docx")
    p = builtin_profiles()["apa-7"]
    a, b = evaluate(p, adm), evaluate(p, adm)
    assert [(r.rule.id, r.status) for r in a.results] == [(r.rule.id, r.status) for r in b.results]
    failed = {r.rule.id for r in a.results if r.status == "fail"}
    assert {
        "page.margin.left",
        "typography.double_spacing",
        "page.page_numbers",
        "references.alphabetical",
        "figures.numbering",
    } <= failed


def test_clean_report_meets_apa_except_citation_style(fixture_docs) -> None:
    for key, kind in (("clean_docx", "docx"), ("clean_pdf", "pdf")):
        r = evaluate(builtin_profiles()["apa-7"], import_document(fixture_docs[key], kind))
        failed = {x.rule.id for x in r.results if x.status == "fail"}
        assert failed == {"references.citation_style"}, (key, failed)  # numeric [1] citations


GUIDELINE = """Thesis Formatting Guidelines.
All pages must use A4 paper. Use margins of 2.5 cm on all sides.
The text must be 12-point Times New Roman and double-spaced.
The abstract must not exceed 300 words. The thesis must include an abstract, introduction, methodology and references.
Number all pages."""


def test_extraction_grounded_in_quotes() -> None:
    cands = {c.rule["id"]: c for c in extract(GUIDELINE)}
    assert {
        "page.paper",
        "page.margin.top",
        "page.margin.left",
        "typography.body_font",
        "typography.body_size",
        "typography.line_spacing",
        "structure.abstract_length",
        "structure.has_introduction",
        "page.page_numbers",
    } <= set(cands)
    assert cands["page.margin.left"].rule["check"] == {
        "op": "equals",
        "property": "margins.left",
        "value": 2.5,
        "unit": "cm",
        "tolerance": 1,
    }
    assert all(c.evidence_verified for c in cands.values())
    for c in cands.values():  # every extracted rule is valid under the schema
        Rule.model_validate(c.rule)


def test_tampered_candidates_are_rejected() -> None:
    c = extract(GUIDELINE)[0]
    invented = Candidate(rule={**c.rule, "check": {**c.rule["check"], "value": 3.0}}, quote=c.quote)
    assert not verify_candidate(invented, GUIDELINE).evidence_verified
    fake_quote = Candidate(rule=c.rule, quote="Use margins of 2.5 cm everywhere, says nobody.")
    assert "Quote not found" in verify_candidate(fake_quote, GUIDELINE).problems[0]
