"""Mutex validation for `dp docs` run flags."""

from pathlib import Path

import pytest

from docspatch.pipelines.docs.flags import RunFlags, analyze_targets, validate_run_flags
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


# --- analyze_targets: pure cost report, no console ---

DOCUMENTED = '"""Module."""\n\n\ndef f():\n    """Doc."""\n    return 1\n'
UNDOCUMENTED = "def f():\n    return 1\n\n\ndef g():\n    return 2\n"


def test_analyze_clean_repo_has_no_rows(tmp_path: Path):
    src = tmp_path / "a.py"
    src.write_text(DOCUMENTED)
    report = analyze_targets([src], tmp_path, {}, "anthropic", "fast")
    assert report.any_targets is False
    assert report.rows == []
    assert report.total_functions == 0


def test_analyze_groups_and_costs_by_file(tmp_path: Path):
    src = tmp_path / "a.py"
    src.write_text(UNDOCUMENTED)
    report = analyze_targets([src], tmp_path, {}, "anthropic", "fast")
    assert report.any_targets is True
    assert [r.rel for r in report.rows] == ["a.py"]
    assert report.total_functions == 3  # module docstring + f + g
    assert report.rows[0].input_tokens > 0
    assert report.total_cost == pytest.approx(report.rows[0].cost)
    assert report.tier == "fast"
