"""``dp readme`` command: target resolution and the no-LLM staleness check."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from docspatch.cli import app
from docspatch.commands.readme import resolve_target
from docspatch.manifest import ChangeManifest
from docspatch.pipelines.readme.pipeline import scope_state

runner = CliRunner()


@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``Path.cwd`` at ``tmp_path`` so commands resolve paths against it."""
    monkeypatch.setattr(Path, "cwd", classmethod(lambda _cls: tmp_path))
    return tmp_path


# --- target resolution ---


def test_resolve_root_defaults_to_repo_readme(fake_repo: Path) -> None:
    scope, out = resolve_target(None, fake_repo)
    assert scope == "."
    assert out == fake_repo.resolve() / "README.md"


def test_resolve_subpackage(fake_repo: Path) -> None:
    (fake_repo / "src" / "auth").mkdir(parents=True)
    scope, out = resolve_target(Path("src/auth"), fake_repo)
    assert scope == "src/auth"
    assert out == fake_repo.resolve() / "src/auth/README.md"


def test_rejects_file_path(fake_repo: Path) -> None:
    (fake_repo / "mod.py").write_text("x = 1\n")
    result = runner.invoke(app, ["readme", "mod.py"])
    assert result.exit_code == 1
    assert "operates on directories" in result.output.lower()


def test_rejects_missing_path(fake_repo: Path) -> None:
    result = runner.invoke(app, ["readme", "ghost"])
    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_rejects_absolute_path(fake_repo: Path) -> None:
    (fake_repo / "pkg").mkdir()
    result = runner.invoke(app, ["readme", str(fake_repo / "pkg")])
    assert result.exit_code == 1
    assert "repo-relative" in result.output.lower()


def test_rejects_check_with_update(fake_repo: Path) -> None:
    result = runner.invoke(app, ["readme", "--check", "--update"])
    assert result.exit_code == 1
    assert "cannot be used together" in result.output


def test_rejects_check_with_remarks(fake_repo: Path) -> None:
    result = runner.invoke(app, ["readme", "--check", "--remarks", "be brief"])
    assert result.exit_code == 1
    assert "cannot be used together" in result.output


# --- `--check` (no model calls) ---


def test_check_stale_when_readme_missing(fake_repo: Path) -> None:
    (fake_repo / "a.py").write_text("x = 1\n")
    result = runner.invoke(app, ["readme", "--check"])
    assert result.exit_code == 1  # absent README needs generation


def test_check_fresh_when_manifest_matches_current(fake_repo: Path) -> None:
    (fake_repo / "a.py").write_text("x = 1\n")
    (fake_repo / "README.md").write_text("# demo\n")
    # A prior successful run would have committed this baseline.
    state = scope_state(fake_repo, ".")
    ChangeManifest(fake_repo).commit("readme", state.hashes)

    result = runner.invoke(app, ["readme", "--check"])
    assert result.exit_code == 0
    assert "up to date" in result.output.lower()


def test_check_stale_after_code_edit(fake_repo: Path) -> None:
    (fake_repo / "a.py").write_text("x = 1\n")
    (fake_repo / "README.md").write_text("# demo\n")
    ChangeManifest(fake_repo).commit("readme", scope_state(fake_repo, ".").hashes)
    (fake_repo / "a.py").write_text("x = 2  # changed\n")

    result = runner.invoke(app, ["readme", "--check"])
    assert result.exit_code == 1
    assert "stale" in result.output.lower()
