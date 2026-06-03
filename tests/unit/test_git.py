"""GitReader: read-only git config and history access."""

import subprocess

from docspatch.utils.git import GitReader


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _repo(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Ada Lovelace")
    _git(tmp_path, "config", "user.email", "ada@example.com")
    return tmp_path


def _commit(repo, rel, body, message):
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)


def test_reads_local_config_value(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Ada Lovelace")
    assert GitReader(tmp_path).config("user.name") == "Ada Lovelace"


def test_returns_none_for_unset_key(tmp_path):
    _git(tmp_path, "init")
    assert GitReader(tmp_path).config("docspatch.nope") is None


def test_is_repo(tmp_path):
    assert GitReader(tmp_path).is_repo() is False
    _git(tmp_path, "init")
    assert GitReader(tmp_path).is_repo() is True


def test_last_commit_touching_returns_none_when_untouched(tmp_path):
    repo = _repo(tmp_path)
    _commit(repo, "a.py", "x = 1\n", "feat: a")
    assert GitReader(repo).last_commit_touching(["README.md"]) is None


def test_last_commit_touching_finds_the_right_commit(tmp_path):
    repo = _repo(tmp_path)
    _commit(repo, "README.md", "# old\n", "docs: readme")
    _commit(repo, "a.py", "x = 1\n", "feat: a")
    sha = GitReader(repo).last_commit_touching(["README.md"])
    head = subprocess.run(
        ["git", "log", "-2", "--format=%H"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.split()
    # The README touch is the *second* commit, not HEAD.
    assert sha == head[1]


def test_commits_since_scopes_to_paths_and_range(tmp_path):
    repo = _repo(tmp_path)
    _commit(repo, "README.md", "# old\n", "docs: readme")
    ref = GitReader(repo).last_commit_touching(["README.md"])
    _commit(repo, "pkg/a.py", "x = 1\n", "feat: a")
    _commit(repo, "notes.txt", "hi\n", "chore: notes")
    _commit(repo, "pkg/b.py", "y = 2\n", "fix: b")

    commits = GitReader(repo).commits_since(ref, [":(glob)**/*.py"])
    subjects = [c.subject for c in commits]
    assert subjects == ["fix: b", "feat: a"]  # newest first, notes.txt excluded


def test_commits_since_null_ref_walks_whole_history(tmp_path):
    repo = _repo(tmp_path)
    _commit(repo, "pkg/a.py", "x = 1\n", "feat: a")
    commits = GitReader(repo).commits_since(None, [":(glob)**/*.py"])
    assert [c.subject for c in commits] == ["feat: a"]
