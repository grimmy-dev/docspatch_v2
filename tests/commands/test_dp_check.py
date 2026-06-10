"""dp check staleness report.

`dp check` reads only — no model calls, no config — so these tests drive the
report functions directly against a tmp_path repo and assert the stale/fresh
verdict and the aggregated return value.
"""

from typer.testing import CliRunner

import docspatch.commands.check as check
from docspatch.cli import app
from docspatch.manifest import ChangeManifest
from docspatch.pipelines.readme.pipeline import scope_state

runner = CliRunner()

_DOCUMENTED = '''"""Module docstring."""


def greet(name: str) -> str:
    """Return a greeting.

    Args:
        name: Who to greet.

    Returns:
        The greeting.
    """
    return f"hi {name}"
'''

_UNDOCUMENTED = "def greet(name):\n    return f'hi {name}'\n"


def _seed_readme_baseline(repo_root) -> None:
    """Commit a readme manifest baseline matching the current sources."""
    state = scope_state(repo_root, ".")
    ChangeManifest(repo_root).commit("readme", state.hashes, state.stamps)


# --- docs ---


def test_check_docs_flags_undocumented(tmp_path):
    (tmp_path / "mod.py").write_text(_UNDOCUMENTED)
    assert check.check_docs(tmp_path) is True


def test_check_docs_clean_when_documented(tmp_path):
    (tmp_path / "mod.py").write_text(_DOCUMENTED)
    assert check.check_docs(tmp_path) is False


def test_check_docs_clean_when_no_python(tmp_path):
    (tmp_path / "notes.txt").write_text("nothing here")
    assert check.check_docs(tmp_path) is False


# --- readme ---


def test_check_readme_missing_is_stale(tmp_path):
    (tmp_path / "mod.py").write_text(_DOCUMENTED)
    assert check.check_readme(tmp_path) is True


def test_check_readme_fresh_after_baseline(tmp_path):
    (tmp_path / "mod.py").write_text(_DOCUMENTED)
    (tmp_path / "README.md").write_text("# project\n")
    _seed_readme_baseline(tmp_path)
    assert check.check_readme(tmp_path) is False


def test_check_readme_stale_when_source_changes(tmp_path):
    (tmp_path / "mod.py").write_text(_DOCUMENTED)
    (tmp_path / "README.md").write_text("# project\n")
    _seed_readme_baseline(tmp_path)
    (tmp_path / "mod.py").write_text(_DOCUMENTED + "\n\ndef extra() -> None:\n    pass\n")
    assert check.check_readme(tmp_path) is True


def test_check_readme_clean_when_no_python(tmp_path):
    (tmp_path / "README.md").write_text("# project\n")
    assert check.check_readme(tmp_path) is False


# --- aggregation ---


def test_report_true_when_anything_stale(tmp_path):
    (tmp_path / "mod.py").write_text(_UNDOCUMENTED)
    assert check.report(tmp_path) is True


def test_report_false_when_all_fresh(tmp_path):
    (tmp_path / "mod.py").write_text(_DOCUMENTED)
    (tmp_path / "README.md").write_text("# project\n")
    _seed_readme_baseline(tmp_path)
    assert check.report(tmp_path) is False


# --- CLI exit codes (pre-commit contract) ---


def test_cli_check_exits_one_when_stale(monkeypatch):
    monkeypatch.setattr("docspatch.commands.check.report", lambda _root: True)
    assert runner.invoke(app, ["check"]).exit_code == 1


def test_cli_check_exits_zero_when_fresh(monkeypatch):
    monkeypatch.setattr("docspatch.commands.check.report", lambda _root: False)
    assert runner.invoke(app, ["check"]).exit_code == 0
