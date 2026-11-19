"""Imports every module that registers a job handler (see services.jobs.runner)."""

from app.services.changes import service as changes  # noqa: F401
from app.services.exports import service as exports  # noqa: F401
from app.services.generation import service as generation  # noqa: F401
from app.services.inspections import service as inspections  # noqa: F401
from app.services.presentations import service as presentations  # noqa: F401
from app.services.processing import analysis  # noqa: F401
from app.services.references import service as references  # noqa: F401
from app.services.standards import service as standards  # noqa: F401
