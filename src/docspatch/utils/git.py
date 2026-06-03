"""Provide helpers for interacting with local git repositories."""

import subprocess
from dataclasses import dataclass
from pathlib import Path

# Field separator for log records: a byte that cannot appear in a commit subject.
_FIELD_SEP = "\x1f"


@dataclass(frozen=True)
class Commit:
    """One commit's hash and subject line."""

    sha: str
    subject: str


class GitReader:
    """Read-only git access scoped to ``repo_root``."""

    def __init__(self, repo_root: Path) -> None:
        """Bind the reader to a repository root.

        Args:
            repo_root: The base directory of the repository.
        """
        self.repo_root = repo_root

    def _capture(self, args: list[str]) -> str | None:
        """Run a git command and return its stdout, or None when it fails.

        Args:
            args: Git arguments after the ``git`` executable.

        Returns:
            Trimmed stdout, or null when git is missing or exits non-zero.
        """
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    def is_repo(self) -> bool:
        """Report whether ``repo_root`` sits inside a git work tree.

        Returns:
            True when git tracks this directory.
        """
        return self._capture(["rev-parse", "--is-inside-work-tree"]) == "true"

    def config(self, key: str) -> str | None:
        """Fetch a configuration value from the local git installation.

        Args:
            key: The git configuration key.

        Returns:
            The configured value or null if unset.
        """
        return self._capture(["config", "--get", key]) or None

    def last_commit_touching(self, pathspecs: list[str]) -> str | None:
        """Return the hash of the most recent commit that changed the given paths.

        Args:
            pathspecs: Git pathspecs to scope the history to.

        Returns:
            The commit hash, or null when no commit ever touched the paths.
        """
        out = self._capture(["log", "-1", "--format=%H", "--", *pathspecs])
        return out or None

    def commits_since(self, ref: str | None, pathspecs: list[str]) -> list[Commit]:
        """List commits after ``ref`` that changed the given paths, newest first.

        Args:
            ref: Exclusive lower bound; null walks the whole history.
            pathspecs: Git pathspecs to scope the history to.

        Returns:
            The matching commits as hash/subject pairs.
        """
        rev_range = f"{ref}..HEAD" if ref else "HEAD"
        out = self._capture(["log", rev_range, f"--format=%H{_FIELD_SEP}%s", "--", *pathspecs])
        if not out:
            return []
        commits: list[Commit] = []
        for line in out.splitlines():
            sha, _, subject = line.partition(_FIELD_SEP)
            commits.append(Commit(sha=sha, subject=subject))
        return commits
