"""Deterministic UDSE evaluation.

``evaluate(profile, adm)`` returns one :class:`RuleResult` per enabled rule. A rule is
``pass`` | ``fail`` | ``not_evaluated``. A rule is never passed by default: if its inputs are
missing (unknown property values, no matching nodes where some are required, unsupported
format, no language model for a soft rubric) the result is ``not_evaluated`` with a reason.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.domain.adm.model import AdmDocument, Paragraph
from app.domain.inspection.checks._util import label_number
from app.domain.inspection.checks.references import CITE_GROUP, NUMERIC_LABEL
from app.domain.inspection.model import Finding
from app.domain.udse.properties import LENGTH_PROPS, Item, norm_text, select, to_pt
from app.domain.udse.schema import Rule, StandardProfile

ENGINE_VERSION = "udse-1.0"
CATEGORY_MAP = {
    "page": "page",
    "typography": "typography",
    "structure": "structure",
    "references": "references",
    "figures_tables": "figures_tables",
    "layout": "layout",
    "slides": "slides",
}
WEIGHT = {"critical": 5.0, "high": 3.0, "medium": 2.0, "low": 1.0, "info": 0.5}
HARD_CAP = 69.0


@dataclass
class Violation:
    item: Item | None
    actual: Any
    detail: str = ""


@dataclass
class RuleResult:
    rule: Rule
    status: str  # pass | fail | not_evaluated
    reason: str = ""
    violations: list[Violation] = field(default_factory=list)
    checked: int = 0


class _NotEvaluated(Exception):
    pass


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:g}"
    if isinstance(v, list):
        return ", ".join(_fmt(x) for x in v)
    return str(v)


def _expected(rule: Rule) -> Any:
    c = rule.check
    if c.op == "in_range":
        lo = f"{c.min:g}" if c.min is not None else "…"
        hi = f"{c.max:g}" if c.max is not None else "…"
        return f"{lo}–{hi} {c.unit if c.unit != 'none' else ''}".strip()  # noqa: RUF001
    if c.values is not None:
        return c.values
    if c.value is not None:
        return f"{_fmt(c.value)} {c.unit}" if c.unit != "none" else c.value
    return c.pattern


def _prop(item: Item, rule: Rule) -> Any:
    assert rule.check.property is not None
    return item.props.get(rule.check.property)


def _cmp_value(rule: Rule, v: Any) -> Any:
    c = rule.check
    if c.property in LENGTH_PROPS:
        return to_pt(v, c.unit)
    return v


def _tol(rule: Rule) -> float:
    c = rule.check
    return to_pt(c.tolerance, c.unit) if c.property in LENGTH_PROPS else c.tolerance


def _eq(rule: Rule, actual: Any, expected: Any) -> bool:
    if isinstance(actual, int | float) and isinstance(expected, int | float) and not isinstance(actual, bool):
        return bool(abs(actual - expected) <= _tol(rule) + 1e-6)
    if rule.check.case_insensitive:
        return bool(norm_text(actual) == norm_text(expected))
    return bool(actual == expected)


def _per_item(rule: Rule, items: list[Item], test) -> RuleResult:  # type: ignore[no-untyped-def]
    known = [i for i in items if _prop(i, rule) is not None]
    if not items:
        raise _NotEvaluated("No matching elements in this document.")
    if not known:
        raise _NotEvaluated(f"“{rule.check.property}” could not be determined for this document.")
    v = [Violation(i, _prop(i, rule)) for i in known if not test(_prop(i, rule))]
    return RuleResult(rule, "fail" if v else "pass", violations=v, checked=len(known))


def _evaluate(rule: Rule, adm: AdmDocument) -> RuleResult:
    c = rule.check
    if adm.source_format not in rule.applies_to:
        raise _NotEvaluated(f"Rule does not apply to {adm.source_format.upper()} files.")
    items = select(adm, rule.selector.node, rule.selector.where)
    op = c.op

    if op == "llm_assess":
        raise _NotEvaluated("Model-assessed rule: no language model is configured.")
    if op == "equals":
        exp = _cmp_value(rule, c.value)
        if (c.property or "").startswith("margins.") and items and all(i.fidelity == "inferred" for i in items):
            # PDF margins are measured from where text reaches, so they can only be too small
            # (text intrudes), never reliably "too large" (ragged-right text, short pages).
            return _per_item(rule, items, lambda a: a >= exp - _tol(rule))
        return _per_item(rule, items, lambda a: _eq(rule, a, exp))
    if op == "not_equals":
        exp = _cmp_value(rule, c.value)
        return _per_item(rule, items, lambda a: not _eq(rule, a, exp))
    if op == "in_set":
        allowed = [_cmp_value(rule, x) for x in (c.values or [])]
        return _per_item(rule, items, lambda a: any(_eq(rule, a, x) for x in allowed))
    if op == "in_range":
        lo = _cmp_value(rule, c.min) if c.min is not None else None
        hi = _cmp_value(rule, c.max) if c.max is not None else None
        t = _tol(rule)
        return _per_item(rule, items, lambda a: (lo is None or a >= lo - t) and (hi is None or a <= hi + t))
    if op == "matches":
        rx = re.compile(c.pattern or "", re.IGNORECASE if c.case_insensitive else 0)
        return _per_item(rule, items, lambda a: bool(rx.search(str(a))))
    if op == "present":
        return RuleResult(
            rule,
            "pass" if items else "fail",
            checked=1,
            violations=[] if items else [Violation(None, None, "not found")],
        )
    if op == "absent":
        return RuleResult(
            rule, "fail" if items else "pass", checked=1, violations=[Violation(i, i.text[:80]) for i in items]
        )
    if op == "count":
        n = len(items)
        ok = (c.min is None or n >= c.min) and (c.max is None or n <= c.max)
        return RuleResult(rule, "pass" if ok else "fail", checked=1, violations=[] if ok else [Violation(None, n)])
    if op in ("max_words", "min_words"):
        if not items:
            raise _NotEvaluated("No matching section in this document.")
        limit = c.max if op == "max_words" else c.min
        v = [
            Violation(i, i.props.get("word_count"))
            for i in items
            if (op == "max_words" and i.props.get("word_count", 0) > (limit or 0))
            or (op == "min_words" and i.props.get("word_count", 0) < (limit or 0))
        ]
        return RuleResult(rule, "fail" if v else "pass", violations=v, checked=len(items))
    if op == "order":
        wanted = [str(x) for x in (c.values or [])]
        seen = [str(i.props.get("role")) for i in items if i.props.get("role") in wanted]
        if len(seen) < 2:
            raise _NotEvaluated("Too few of the listed sections are present to check their order.")
        ranks = [wanted.index(r) for r in seen]
        ok = ranks == sorted(ranks)
        return RuleResult(
            rule,
            "pass" if ok else "fail",
            checked=1,
            violations=[] if ok else [Violation(None, seen, "sections out of order")],
        )
    if op == "consistent":
        known = [i for i in items if _prop(i, rule) is not None]
        if len(known) < 2:
            raise _NotEvaluated("Fewer than two elements to compare.")
        values: dict[Any, int] = {}
        for i in known:
            values[norm_text(_prop(i, rule))] = values.get(norm_text(_prop(i, rule)), 0) + 1
        main = max(values, key=lambda k: values[k])
        v = [Violation(i, _prop(i, rule)) for i in known if norm_text(_prop(i, rule)) != main]
        return RuleResult(rule, "fail" if v else "pass", violations=v, checked=len(known))
    if op == "all_have":
        prop = c.property or "has_caption"
        if not items:
            return RuleResult(rule, "pass", checked=0, reason="No matching elements.")
        v = [Violation(i, False) for i in items if not i.props.get(prop)]
        return RuleResult(rule, "fail" if v else "pass", violations=v, checked=len(items))
    if op == "sequence":
        nums = [(i, label_number(i.props.get(c.property or "number"))) for i in items]
        nums = [(i, n) for i, n in nums if n is not None]
        if not nums:
            raise _NotEvaluated("No numbered elements found.")
        v = [Violation(i, n, f"expected {k + 1}") for k, (i, n) in enumerate(nums) if n != k + 1]
        if c.pattern:  # label style, e.g. roman numerals for IEEE tables
            rx = re.compile(c.pattern)
            v += [
                Violation(i, i.props.get(c.property or "number"), "wrong numbering style")
                for i, _ in nums
                if not rx.fullmatch(str(i.props.get(c.property or "number")))
            ]
        return RuleResult(rule, "fail" if v else "pass", violations=v[:20], checked=len(nums))
    if op == "referenced_in_text":
        body = " ".join(b.text for b in adm.body if isinstance(b, Paragraph))
        caps = [i for i in items if i.props.get("number")]
        if not caps:
            return RuleResult(rule, "pass", checked=0, reason="No numbered captions.")
        v = []
        for i in caps:
            word = r"(fig\.?|figure)" if i.props.get("target_kind") == "figure" else r"table"
            if not re.search(rf"\b{word}\s*{re.escape(str(i.props['number']))}\b", body, re.IGNORECASE):
                v.append(Violation(i, "not referenced"))
        return RuleResult(rule, "fail" if v else "pass", violations=v, checked=len(caps))
    if op == "citation_style":
        body = " ".join(b.text for b in adm.body if isinstance(b, Paragraph) and b.role != "reference_entry")
        numeric = len(CITE_GROUP.findall(body))
        author_year = len(
            re.findall(r"\([A-Z][A-Za-z'\-]+(?: et al\.)?(?:,| and| &)[^()]{0,40}\b(19|20)\d{2}[a-z]?\)", body)
        )
        if numeric + author_year == 0:
            raise _NotEvaluated("No in-text citations found.")
        style = "numeric" if numeric >= author_year else "author_year"
        ok = style == c.value
        return RuleResult(
            rule,
            "pass" if ok else "fail",
            checked=numeric + author_year,
            violations=[] if ok else [Violation(None, style)],
        )
    if op == "reference_order":
        entries = [b for b in adm.body if isinstance(b, Paragraph) and b.role == "reference_entry" and b.text.strip()]
        if len(entries) < 2:
            raise _NotEvaluated("Fewer than two reference entries.")
        if c.value == "numeric":
            labels = [NUMERIC_LABEL.match(e.text) for e in entries]
            ref_nums = [int(m.group(1) or m.group(2)) for m in labels if m]
            if len(ref_nums) < len(entries) * 0.8:
                return RuleResult(
                    rule, "fail", checked=len(entries), violations=[Violation(None, "unnumbered entries")]
                )
            ok = ref_nums == list(range(1, len(ref_nums) + 1))
        else:
            keys = [re.sub(r"[^a-z]", "", e.text.lower())[:20] for e in entries]
            ok = keys == sorted(keys)
        return RuleResult(
            rule,
            "pass" if ok else "fail",
            checked=len(entries),
            violations=[] if ok else [Violation(None, "out of order")],
        )
    raise _NotEvaluated(f"Operator {op} is not supported.")


@dataclass
class UdseResult:
    profile: StandardProfile
    results: list[RuleResult]
    findings: list[Finding]
    compliance: dict[str, Any]
    engine_version: str = ENGINE_VERSION


def evaluate(profile: StandardProfile, adm: AdmDocument) -> UdseResult:
    results: list[RuleResult] = []
    for rule in profile.rules:
        if not rule.enabled:
            continue
        try:
            results.append(_evaluate(rule, adm))
        except _NotEvaluated as exc:
            results.append(RuleResult(rule, "not_evaluated", reason=str(exc)))
    findings = [f for r in results if r.status == "fail" for f in _findings(r, adm)]
    return UdseResult(profile=profile, results=results, findings=findings, compliance=compliance(profile, results))


def _findings(r: RuleResult, adm: AdmDocument) -> list[Finding]:
    rule = r.rule
    src = rule.provenance
    cite = f" Source: {src.source}{', ' + src.locator if src and src.locator else ''}." if src else ""
    if src and src.verification in ("unverified", "secondary"):
        cite += (
            " (Built-in value checked against secondary sources only — confirm with your venue.)"
            if src.verification == "secondary"
            else " (Unverified — confirm with your venue.)"
        )
    out = []
    for v in r.violations[:25]:
        actual = v.actual
        if (
            rule.check.property in LENGTH_PROPS
            and isinstance(actual, int | float)
            and rule.check.unit in ("in", "mm", "cm")
        ):
            actual = round(actual / to_pt(1, rule.check.unit), 2)
            actual_s = f"{actual:g} {rule.check.unit}"
        else:
            actual_s = _fmt(actual)
        msg = (rule.message or f"{rule.title}: found {{actual}}, expected {{expected}}.").format(
            actual=actual_s, expected=_fmt(_expected(rule))
        )
        out.append(
            Finding(
                code=f"UDSE.{rule.id}",
                category=CATEGORY_MAP[rule.category],  # type: ignore[arg-type]
                severity=rule.severity,
                message=msg,
                explanation=f"{rule.title} ({rule.kind} rule).{cite}",
                recommendation=rule.fix.hint or f"Change it to {_fmt(_expected(rule))}.",
                node_ids=[v.item.id] if v.item and v.item.id and not v.item.id.startswith("ps") else [],
                page=v.item.page if v.item else None,
                expected=_expected(rule),
                actual=actual if not isinstance(actual, Item) else None,
                confidence=1.0 if (v.item is None or v.item.fidelity == "exact") else 0.7,
                fix_available=rule.fix.auto,
                rule_id=rule.id,
                constraint=rule.kind,
            )
        )
    return out


def compliance(profile: StandardProfile, results: list[RuleResult]) -> dict[str, Any]:
    ev = [r for r in results if r.status != "not_evaluated"]
    total = sum(WEIGHT[r.rule.severity] for r in ev)
    passed = sum(WEIGHT[r.rule.severity] for r in ev if r.status == "pass")
    hard_fail = sum(1 for r in ev if r.rule.kind == "hard" and r.status == "fail")
    raw = round(100 * passed / total, 1) if total else None
    score_v = min(raw, HARD_CAP) if (raw is not None and hard_fail) else raw
    verdict = (
        "not evaluated"
        if score_v is None
        else "not compliant"
        if hard_fail
        else "compliant"
        if score_v >= 85
        else "partially compliant"
    )
    return {
        "standard": f"{profile.name} {profile.version}",
        "slug": profile.slug,
        "score": score_v,
        "raw_score": raw,
        "verdict": verdict,
        "hard_pass": sum(1 for r in ev if r.rule.kind == "hard" and r.status == "pass"),
        "hard_fail": hard_fail,
        "soft_pass": sum(1 for r in ev if r.rule.kind == "soft" and r.status == "pass"),
        "soft_fail": sum(1 for r in ev if r.rule.kind == "soft" and r.status == "fail"),
        "not_evaluated": sum(1 for r in results if r.status == "not_evaluated"),
        "cap_applied": bool(hard_fail and raw is not None and raw > HARD_CAP),
    }
