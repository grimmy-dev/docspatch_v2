"""Runs and parses shell executions of git configuration and repository history queries."""

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
        """Bind the git client to a specific local repository workspace.

        Args:
            repo_root: File system path of the Git workspace root.
        """
        self.repo_root = repo_root

    def _capture(self, args: list[str]) -> str | None:
        """Run a git subprocess and return its stripped standard output.

        Args:
            args: Command-line options to append after the git command.

        Returns:
            Trimmed standard output of the command, or None if the call fails or git exits non-zero.
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
        """Check if the workspace is located inside an initialized Git work tree.

        Returns:
            True if git reports being in a workspace, False otherwise.
        """
        return self._capture(["rev-parse", "--is-inside-work-tree"]) == "true"

    def config(self, key: str) -> str | None:
        """Retrieve a key value from local git configuration records.

        Args:
            key: The configuration setting path to query.

        Returns:
            The configured value string, or None if the key is unset.
        """
        return self._capture(["config", "--get", key]) or None

    def last_commit_touching(self, pathspecs: list[str]) -> str | None:
        """Find the commit hash of the latest commit that modified selected pathspecs.

        Args:
            pathspecs: Workspace paths to filter the history against.

        Returns:
            The latest matching commit SHA hash, or None if no commits match.
        """
        out = self._capture(["log", "-1", "--format=%H", "--", *pathspecs])
        return out or None

    def commits_since(self, ref: str | None, pathspecs: list[str]) -> list[Commit]:
        """Query Git log to retrieve commits modified after a specific revision.

        Args:
            ref: Exclusive starting revision boundary, or null to walk the whole history.
            pathspecs: List of repository patterns to filter the log.

        Returns:
            List of Commit dataclasses containing matching hash and subject line pairs.
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
