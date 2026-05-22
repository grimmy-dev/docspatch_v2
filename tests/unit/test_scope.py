"""Scope resolution: validate explicit paths, expand dirs, filter ignored."""

from pathlib import Path

import pytest

from docspatch.utils.errors import PathError
from docspatch.utils.ignore import DocsIgnore
from docspatch.utils.scope import resolve_scope


def make_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    """Materialise a fake repo on disk under ``tmp_path``."""
    for rel, body in files.items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body)
    return tmp_path


def test_resolves_relative_python_file(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {"src/a.py": "x=1\n"})
    out = resolve_scope([Path("src/a.py")], repo, ignore=DocsIgnore.empty())
    assert out == [(repo / "src/a.py").resolve()]


def test_absolute_path_rejected_with_relative_hint(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {"src/a.py": ""})
    abs_path = (repo / "src/a.py").resolve()
    with pytest.raises(PathError, match="repo-relative"):
        resolve_scope([abs_path], repo, ignore=DocsIgnore.empty())


def test_missing_path_rejected(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {})
    with pytest.raises(PathError, match="not found"):
        resolve_scope([Path("ghost.py")], repo, ignore=DocsIgnore.empty())


def test_outside_repo_rejected(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {})
    other = tmp_path.parent / "elsewhere.py"
    other.write_text("")
    with pytest.raises(PathError, match="outside the repo"):
        resolve_scope([other], repo, ignore=DocsIgnore.empty())


def test_non_python_file_rejected(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {"notes.txt": "hi"})
    with pytest.raises(PathError, match="Not a Python file"):
        resolve_scope([Path("notes.txt")], repo, ignore=DocsIgnore.empty())


def test_untracked_new_file_accepted(tmp_path: Path) -> None:
    """New / never-git-added files must be documentable (bug fix)."""
    repo = make_repo(tmp_path, {"src/new.py": ""})
    out = resolve_scope([Path("src/new.py")], repo, ignore=DocsIgnore.empty())
    assert out == [(repo / "src/new.py").resolve()]


def test_ignored_explicit_file_rejected(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {"vendored/a.py": ""})
    ignore = load_lines("vendored/")
    with pytest.raises(PathError, match=".docsignore"):
        resolve_scope([Path("vendored/a.py")], repo, ignore=ignore)


def test_no_ignore_bypasses_filter(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {"vendored/a.py": ""})
    ignore = load_lines("vendored/")
    out = resolve_scope(
        [Path("vendored/a.py")],
        repo,
        ignore=ignore,
        no_ignore=True,
    )
    assert out == [(repo / "vendored/a.py").resolve()]


def test_directory_walks_filesystem_minus_ignored(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path,
        {
            "src/a.py": "",
            "src/b.py": "",
            "src/vendored/c.py": "",
            "src/notes.txt": "",
        },
    )
    ignore = load_lines("src/vendored/")
    out = resolve_scope([Path("src")], repo, ignore=ignore)
    assert sorted(p.name for p in out) == ["a.py", "b.py"]


def load_lines(*lines: str) -> DocsIgnore:
    """Build a DocsIgnore from raw lines (without defaults), for focused tests."""
    import pathspec

    return DocsIgnore(spec=pathspec.PathSpec.from_lines("gitignore", lines))
