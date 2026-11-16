"""Outline templates for each document type (deterministic; no model needed).

Each entry is (title, level, share of the word budget). Shares are normalised, so the target
word count is distributed sensibly; the user can edit everything afterwards.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

KINDS: dict[str, dict[str, Any]] = {
    "research_paper": {
        "label": "Research paper",
        "words": 4000,
        "outline": [
            ("Abstract", 1, 0.05),
            ("Introduction", 1, 0.15),
            ("Related Work", 1, 0.15),
            ("Methodology", 1, 0.2),
            ("Results", 1, 0.2),
            ("Discussion", 1, 0.15),
            ("Conclusion", 1, 0.1),
            ("References", 1, 0.0),
        ],
    },
    "academic_report": {
        "label": "Academic report",
        "words": 3000,
        "outline": [
            ("Abstract", 1, 0.06),
            ("Introduction", 1, 0.15),
            ("Background", 1, 0.15),
            ("Method", 1, 0.2),
            ("Findings", 1, 0.24),
            ("Conclusion", 1, 0.1),
            ("Recommendations", 1, 0.1),
            ("References", 1, 0.0),
        ],
    },
    "technical_documentation": {
        "label": "Technical documentation",
        "words": 2500,
        "outline": [
            ("Overview", 1, 0.12),
            ("Requirements", 1, 0.12),
            ("Installation", 1, 0.14),
            ("Configuration", 1, 0.16),
            ("Usage", 1, 0.2),
            ("Architecture", 1, 0.14),
            ("Troubleshooting", 1, 0.12),
        ],
    },
    "business_proposal": {
        "label": "Business proposal",
        "words": 2000,
        "outline": [
            ("Executive Summary", 1, 0.12),
            ("Problem Statement", 1, 0.14),
            ("Proposed Solution", 1, 0.22),
            ("Scope and Deliverables", 1, 0.14),
            ("Timeline", 1, 0.1),
            ("Budget", 1, 0.1),
            ("Team", 1, 0.08),
            ("Next Steps", 1, 0.1),
        ],
    },
    "project_report": {
        "label": "Project report",
        "words": 3000,
        "outline": [
            ("Summary", 1, 0.08),
            ("Introduction", 1, 0.12),
            ("Objectives", 1, 0.1),
            ("Methodology", 1, 0.18),
            ("Implementation", 1, 0.2),
            ("Results", 1, 0.17),
            ("Conclusion and Future Work", 1, 0.15),
            ("References", 1, 0.0),
        ],
    },
    "article": {
        "label": "Article",
        "words": 1200,
        "outline": [("Introduction", 1, 0.2), ("Main Points", 1, 0.55), ("Conclusion", 1, 0.25)],
    },
    "essay": {
        "label": "Essay",
        "words": 1500,
        "outline": [
            ("Introduction", 1, 0.15),
            ("Argument", 1, 0.35),
            ("Counterarguments", 1, 0.2),
            ("Analysis", 1, 0.15),
            ("Conclusion", 1, 0.15),
            ("Works Cited", 1, 0.0),
        ],
    },
    "formal_letter": {
        "label": "Formal letter",
        "words": 350,
        "outline": [
            ("Sender and Date", 2, 0.0),
            ("Recipient", 2, 0.0),
            ("Subject", 2, 0.05),
            ("Body", 2, 0.85),
            ("Closing", 2, 0.1),
        ],
    },
    "meeting_report": {
        "label": "Meeting report",
        "words": 800,
        "outline": [
            ("Meeting Details", 1, 0.1),
            ("Attendees", 1, 0.08),
            ("Agenda", 1, 0.12),
            ("Discussion", 1, 0.4),
            ("Decisions", 1, 0.15),
            ("Action Items", 1, 0.15),
        ],
    },
    "professional_document": {
        "label": "Professional document",
        "words": 1500,
        "outline": [("Purpose", 1, 0.15), ("Background", 1, 0.2), ("Details", 1, 0.45), ("Next Steps", 1, 0.2)],
    },
}

TONES = ("formal", "academic", "professional", "neutral", "persuasive", "friendly")


def new_outline(kind: str, word_target: int | None = None) -> list[dict[str, Any]]:
    tpl = KINDS[kind]
    total = word_target or tpl["words"]
    shares = [s for _, _, s in tpl["outline"]]
    norm = sum(shares) or 1.0
    return [
        {
            "id": uuid.uuid4().hex[:10],
            "title": title,
            "level": level,
            "target_words": round(total * share / norm / 10) * 10,
            "notes": "",
        }
        for title, level, share in tpl["outline"]
    ]


def is_references(title: str) -> bool:
    return bool(re.fullmatch(r"(references|bibliography|works cited|sources)", title.strip().lower()))
