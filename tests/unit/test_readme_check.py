"""README staleness: git-driven verdict, type hints, no model calls."""

import subprocess

from docspatch.pipelines.readme.check import build_report, likely_noop, py_pathspec


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _repo(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Ada")
    _git(tmp_path, "config", "user.email", "ada@example.com")
    return tmp_path


def _commit(repo, rel, body, message):
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)


def test_py_pathspec_root_and_subpackage():
    assert py_pathspec(".") == ":(glob)**/*.py"
    assert py_pathspec("src/auth/") == ":(glob)src/auth/**/*.py"


def test_likely_noop_flags_low_impact_types_only():
    assert likely_noop("docs: tweak")
    assert likely_noop("fix(core): bug")
    assert likely_noop("chore!: drop py3.13")
    assert not likely_noop("feat: new command")
    assert not likely_noop("just a plain message")


def test_uncommitted_readme_needs_generation(tmp_path):
    repo = _repo(tmp_path)
    _commit(repo, "pkg/a.py", "x = 1\n", "feat: a")
    report = build_report(repo, ".", "README.md")
    assert report.committed is False
    assert report.stale is True


def test_readme_current_when_no_later_code_commits(tmp_path):
    repo = _repo(tmp_path)
    _commit(repo, "pkg/a.py", "x = 1\n", "feat: a")
    _commit(repo, "README.md", "# demo\n", "docs: readme")
    report = build_report(repo, ".", "README.md")
    assert report.committed is True
    assert report.stale is False


def test_readme_stale_lists_later_code_commits_with_hints(tmp_path):
    repo = _repo(tmp_path)
    _commit(repo, "README.md", "# demo\n", "docs: readme")
    _commit(repo, "pkg/a.py", "x = 1\n", "feat: big feature")
    _commit(repo, "pkg/b.py", "y = 2\n", "fix: small bug")
    report = build_report(repo, ".", "README.md")
    assert report.stale is True
    subjects = [(h.commit.subject, h.likely_noop) for h in report.hints]
    assert ("feat: big feature", False) in subjects
    assert ("fix: small bug", True) in subjects


def test_scope_limits_commits_to_subtree(tmp_path):
    repo = _repo(tmp_path)
    _commit(repo, "src/auth/README.md", "# auth\n", "docs: auth readme")
    _commit(repo, "src/auth/login.py", "x = 1\n", "feat: login")
    _commit(repo, "src/db/pool.py", "y = 2\n", "feat: pool")
    report = build_report(repo, "src/auth", "src/auth/README.md")
    assert [h.commit.subject for h in report.hints] == ["feat: login"]
