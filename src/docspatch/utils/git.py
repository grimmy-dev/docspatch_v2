"""Runs and parses shell executions of git configuration queries."""

import subprocess
from pathlib import Path


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

    def config(self, key: str) -> str | None:
        """Retrieve a key value from local git configuration records.

        Args:
            key: The configuration setting path to query.

        Returns:
            The configured value string, or None if the key is unset.
        """
        return self._capture(["config", "--get", key]) or None
