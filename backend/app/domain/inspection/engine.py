"""Check registry and runner.

A check is a pure function ``(ctx) -> list[Finding]``. It may raise :class:`NotEvaluated`
when its inputs are missing (e.g. no rendered pages); that is reported, never counted as a pass.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from app.domain.inspection.locate import Locator
from app.domain.inspection.model import SEVERITY_ORDER, Finding, InspectContext

ENGINE_VERSION = "inspect-1.0"


class NotEvaluated(Exception):
    """The check could not run on this document; ``str(exc)`` says why."""


Check = Callable[[InspectContext], list[Finding]]


@dataclass(frozen=True)
class CheckInfo:
    code: str
    fn: Check
    formats: tuple[str, ...]


CHECKS: list[CheckInfo] = []


def check(code: str, formats: tuple[str, ...] = ("docx", "pdf", "generated")) -> Callable[[Check], Check]:
    def register(fn: Check) -> Check:
        CHECKS.append(CheckInfo(code=code, fn=fn, formats=formats))
        return fn

    return register


@dataclass
class InspectionResult:
    findings: list[Finding]
    not_evaluated: list[dict[str, str]] = field(default_factory=list)
    checks_run: int = 0
    engine_version: str = ENGINE_VERSION


def inspect(ctx: InspectContext) -> InspectionResult:
    from app.domain.inspection import checks  # noqa: F401  (registers checks)

    locator = Locator(ctx.adm, ctx.layout)
    findings: list[Finding] = []
    skipped: list[dict[str, str]] = []
    ran = 0
    for info in CHECKS:
        if ctx.adm.source_format not in info.formats:
            continue
        try:
            out = info.fn(ctx)
            ran += 1
        except NotEvaluated as exc:
            skipped.append({"check": info.code, "reason": str(exc)})
            continue
        for f in out:
            if f.page is None and f.node_ids:
                page, bbox = locator.locate(f.node_ids[0])
                f.page = page
                f.bbox = f.bbox or bbox
            if not f.location:
                f.location = (
                    locator.label(f.node_ids[0], f.page)
                    if f.node_ids
                    else (f"page {f.page + 1}" if f.page is not None else "whole document")
                )
            f.confidence = min(f.confidence, ctx.confidence)
            findings.append(f)
    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.page if f.page is not None else 10**6))
    return InspectionResult(findings=findings, not_evaluated=skipped, checks_run=ran)
