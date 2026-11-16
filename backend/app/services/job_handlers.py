"""Imports every module that registers a job handler (see services.jobs.runner)."""

from app.services.changes import service as changes  # noqa: F401
from app.services.inspections import service as inspections  # noqa: F401
from app.services.processing import analysis  # noqa: F401
from app.services.standards import service as standards  # noqa: F401
