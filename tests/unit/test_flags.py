"""Mutex validation for `dp docs` run flags."""

from pathlib import Path

import pytest

from docspatch.pipelines.docs.flags import RunFlags, validate_run_flags
from docspatch.utils.errors import ConfigError

PATHS = (Path("a.py"),)


def test_paths_only_ok():
    validate_run_flags(RunFlags(paths=PATHS))


def test_resume_only_ok():
    validate_run_flags(RunFlags(resume=True))


@pytest.mark.parametrize(
    "flags",
    [
        RunFlags(paths=PATHS, check=True, update=True),
        RunFlags(paths=PATHS, check=True, remarks="x"),
        RunFlags(check=True, resume=True),
        RunFlags(update=True, resume=True),
        RunFlags(paths=PATHS, resume=True),
    ],
)
def test_conflicting_flags_rejected(flags):
    with pytest.raises(ConfigError, match="cannot be used together"):
        validate_run_flags(flags)


@pytest.mark.parametrize(
    "flags",
    [
        RunFlags(),  # bare `dp docs` -> whole repo
        RunFlags(paths=PATHS, check=True),
        RunFlags(paths=PATHS, update=True, remarks="x"),
        RunFlags(resume=True, remarks="x"),
    ],
)
def test_allowed_combinations(flags):
    validate_run_flags(flags)
