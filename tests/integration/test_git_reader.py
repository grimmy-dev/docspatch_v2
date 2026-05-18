"""GitReader deep module behavior tests (Priority 3) — real tmp git repos, no network."""

import subprocess
from pathlib import Path

import pytest

from docspatch.utils.errors import GitError
from docspatch.utils.git_reader import GitReader


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@test.com"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], check=True, capture_output=True)


def _commit_file(repo: Path, rel: str, content: str = "") -> None:
    f = repo / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content)
    subprocess.run(["git", "-C", str(repo), "add", rel], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "add file"], check=True, capture_output=True)


def test_git_find_repo_root_correct(tmp_path):
    _init_repo(tmp_path)
    subdir = tmp_path / "src" / "deep"
    subdir.mkdir(parents=True)

    reader = GitReader(cwd=subdir)
    assert reader.find_repo_root() == tmp_path


def test_git_find_repo_root_from_repo_root(tmp_path):
    _init_repo(tmp_path)
    reader = GitReader(cwd=tmp_path)
    assert reader.find_repo_root() == tmp_path


def test_git_list_tracked_files_returns_only_tracked_py(tmp_path):
    _init_repo(tmp_path)
    _commit_file(tmp_path, "foo.py", "x = 1")
    _commit_file(tmp_path, "bar.py", "y = 2")
    _commit_file(tmp_path, "README.md", "docs")

    reader = GitReader(cwd=tmp_path)
    files = reader.list_tracked_files()
    assert "foo.py" in files
    assert "bar.py" in files
    assert "README.md" not in files


def test_git_list_tracked_files_empty_repo(tmp_path):
    _init_repo(tmp_path)
    reader = GitReader(cwd=tmp_path)
    assert reader.list_tracked_files() == []


def test_git_error_outside_repo(tmp_path):
    reader = GitReader(cwd=tmp_path)
    with pytest.raises(GitError):
        reader.find_repo_root()


def test_git_error_on_bad_ref(tmp_path):
    _init_repo(tmp_path)
    _commit_file(tmp_path, "a.py")
    reader = GitReader(cwd=tmp_path)
    with pytest.raises(GitError):
        reader.get_activity_signals(since_ref="nonexistent-branch-xyz")
