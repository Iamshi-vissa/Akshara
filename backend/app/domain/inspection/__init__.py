"""Deterministic document inspection (ARCHITECTURE.md §4, Phase 3)."""

from app.domain.inspection.engine import CHECKS, InspectionResult, inspect
from app.domain.inspection.model import Finding, InspectContext, Severity

__all__ = ["CHECKS", "Finding", "InspectContext", "InspectionResult", "Severity", "inspect"]
