"""``dp docs`` command behavior. Each test fakes ``Path.cwd`` so nothing lands in the repo."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from docspatch.cli import app

runner = CliRunner()


@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``Path.cwd`` at ``tmp_path`` so commands resolve paths against it."""
    monkeypatch.setattr(Path, "cwd", classmethod(lambda _cls: tmp_path))
    return tmp_path


def test_rejects_missing_file(fake_repo: Path) -> None:
    result = runner.invoke(app, ["docs", "ghost.py"])
    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_rejects_non_python_file(fake_repo: Path) -> None:
    (fake_repo / "notes.txt").write_text("hi")
    result = runner.invoke(app, ["docs", "notes.txt"])
    assert result.exit_code == 1
    assert "not a python file" in result.output.lower()


def test_rejects_absolute_path(fake_repo: Path) -> None:
    (fake_repo / "a.py").write_text("")
    result = runner.invoke(app, ["docs", str(fake_repo / "a.py")])
    assert result.exit_code == 1
    assert "repo-relative" in result.output.lower()


def test_rejects_path_outside_repo(fake_repo: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    other = tmp_path_factory.mktemp("elsewhere") / "outside.py"
    other.write_text("")
    result = runner.invoke(app, ["docs", str(other)])
    assert result.exit_code == 1
    assert "outside the repo" in result.output.lower()


def test_rejects_conflicting_flags(fake_repo: Path) -> None:
    (fake_repo / "a.py").write_text("")
    result = runner.invoke(app, ["docs", "--check", "--update", "a.py"])
    assert result.exit_code == 1
    assert "cannot be used together" in result.output


def test_rejects_resume_with_paths(fake_repo: Path) -> None:
    (fake_repo / "a.py").write_text("")
    result = runner.invoke(app, ["docs", "--resume", "a.py"])
    assert result.exit_code == 1
    assert "cannot be used together" in result.output


# --- `--check` preview ---

DOCUMENTED = 'def f():\n    """Does a thing."""\n    return 1\n'
UNDOCUMENTED = "def f():\n    return 1\n"


def test_check_clean_repo(fake_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from docspatch.cache import DocsCache
    from docspatch.pipelines.docs.flags import preview_check

    src = fake_repo / "a.py"
    src.write_text(DOCUMENTED)
    assert preview_check([src], fake_repo, DocsCache(fake_repo), "anthropic", "fast") is False
    assert "All Python files documented" in capsys.readouterr().out


def test_check_dirty_repo_shows_table(fake_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from docspatch.cache import DocsCache
    from docspatch.pipelines.docs.flags import preview_check

    src = fake_repo / "a.py"
    src.write_text(UNDOCUMENTED)
    assert preview_check([src], fake_repo, DocsCache(fake_repo), "anthropic", "fast") is True

    out = capsys.readouterr().out
    assert "a.py" in out  # table lists the file
    assert "fast" in out  # header shows the tier
    assert "dp docs" in out  # suggests the command to document them
