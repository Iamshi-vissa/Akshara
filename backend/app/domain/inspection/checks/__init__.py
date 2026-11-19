"""Importing this package registers every inspection check."""

from app.domain.inspection.checks import (  # noqa: F401
    figures,
    formatting,
    page,
    references,
    slides,
    structure,
    visual,
)
