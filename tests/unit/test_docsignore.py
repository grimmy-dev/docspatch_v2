""".docsignore matcher behaviour."""

from pathlib import Path

from docspatch.utils.ignore import DocsIgnore, load_docsignore


def test_defaults_match_common_noise() -> None:
    ig = DocsIgnore.defaults()
    assert ig.matches("tests/foo.py")
    assert ig.matches("pkg/__pycache__/m.cpython.pyc")
    assert ig.matches(".venv/lib/x.py")
    assert ig.matches("build/x.py")
    assert ig.matches("conftest.py")
    assert not ig.matches("src/main.py")


def test_missing_user_file_still_applies_defaults(tmp_path: Path) -> None:
    ig = load_docsignore(tmp_path)
    assert ig.matches("tests/foo.py")
    assert not ig.matches("src/main.py")


def test_user_pattern_extends_defaults(tmp_path: Path) -> None:
    (tmp_path / ".docsignore").write_text("*.gen.py\nvendored/\n")
    ig = load_docsignore(tmp_path)
    assert ig.matches("pkg/module.gen.py")
    assert ig.matches("vendored/b.py")
    assert ig.matches("tests/foo.py")
    assert not ig.matches("src/main.py")


def test_blank_and_comment_lines_skipped(tmp_path: Path) -> None:
    (tmp_path / ".docsignore").write_text("# comment\n\nlogs/\n")
    ig = load_docsignore(tmp_path)
    assert ig.matches("logs/a.py")
    assert not ig.matches("src/a.py")


def test_filter_paths_drops_matches(tmp_path: Path) -> None:
    (tmp_path / ".docsignore").write_text("vendored/\n")
    ig = load_docsignore(tmp_path)
    kept = ig.filter(["src/a.py", "vendored/b.py", "tests/c.py", "src/d.py"])
    assert kept == ["src/a.py", "src/d.py"]


def test_gitignore_patterns_folded_in(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("secrets/\n*.log\n")
    ig = load_docsignore(tmp_path)
    assert ig.matches("secrets/key.py")
    assert ig.matches("app.log")
    assert not ig.matches("src/main.py")


def test_empty_matcher_matches_nothing() -> None:
    ig = DocsIgnore.empty()
    assert ig.filter(["a.py", "tests/b.py"]) == ["a.py", "tests/b.py"]
    assert ig.matches("tests/b.py") is False
