"""What the running build can actually do.

The frontend uses this to show unbuilt modules as unavailable instead of faking them
(engineering rule: never build a fake working interface). ``COMPLETED_PHASE`` is raised only
when a phase is implemented *and* verified; ``CONDITIONAL`` features additionally depend on
configuration (e.g. an LLM provider) and say so.
"""

from __future__ import annotations

from app.core.config import Settings
from app.schemas.system import Capability

COMPLETED_PHASE = 5

_ALL: list[tuple[str, str, int, str]] = [
    ("upload", "Secure upload & library", 1, "DOCX, PDF and PPTX with content-based validation."),
    ("versions", "Immutable originals & versions", 1, "Originals are stored once and never overwritten."),
    ("preview", "Document parsing & preview", 2, "Canonical document model and page rendering."),
    ("inspect", "Inspect document", 3, "Structural and formatting defects with severity levels."),
    ("standards", "Apply standard (UDSE)", 4, "IEEE, APA, MLA and custom rule profiles."),
    ("edit", "Edit & auto-correct", 5, "Tracked, approval-gated changes."),
    ("create", "Create document", 6, "Outline-first generation with DOCX/PDF export."),
    ("presentations", "Generate presentation", 7, "Themed PPTX with slide validation."),
    ("visual", "Visual quality", 8, "Render-based layout defect detection."),
    ("research", "References & research", 9, "Verified citations, never fabricated."),
]

CAPABILITIES: list[Capability] = [
    Capability(key=k, label=label, available=phase <= COMPLETED_PHASE, phase=phase, note=note)
    for k, label, phase, note in _ALL
]


def capabilities_for(settings: Settings) -> list[Capability]:
    """Phase-based capabilities plus features that also depend on server configuration."""
    grammar = bool(settings.languagetool_url)
    llm = settings.llm_provider != "none"
    return [
        *CAPABILITIES,
        Capability(
            key="grammar",
            label="Grammar & spelling",
            available=grammar and COMPLETED_PHASE >= 5,
            phase=5,
            note="Self-hosted LanguageTool."
            if grammar
            else "Not configured on this server (AKSHARA_LANGUAGETOOL_URL).",
        ),
        Capability(
            key="ai_edit",
            label="AI editing assistant",
            available=llm and COMPLETED_PHASE >= 5,
            phase=5,
            note=f"Model: {settings.llm_model}." if llm else "Not configured on this server (AKSHARA_LLM_PROVIDER).",
        ),
        Capability(
            key="ai_generate",
            label="AI document generation",
            available=llm and COMPLETED_PHASE >= 6,
            phase=6,
            note=f"Model: {settings.llm_model}." if llm else "Not configured on this server (AKSHARA_LLM_PROVIDER).",
        ),
    ]
