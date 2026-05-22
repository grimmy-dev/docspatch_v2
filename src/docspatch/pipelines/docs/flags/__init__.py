"""Run-level flags for ``dp docs``: data shape, mutex validation, flag behaviours."""

from docspatch.pipelines.docs.flags.check import preview_check
from docspatch.pipelines.docs.flags.models import RunFlags
from docspatch.pipelines.docs.flags.remarks import resolve_remarks
from docspatch.pipelines.docs.flags.validate import validate_run_flags

__all__ = ["RunFlags", "preview_check", "resolve_remarks", "validate_run_flags"]
