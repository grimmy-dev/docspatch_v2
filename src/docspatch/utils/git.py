"""Provide helpers for interacting with local git repositories."""

import subprocess
from pathlib import Path


class GitReader:
    """Read-only git access scoped to ``repo_root``."""

    def __init__(self, repo_root: Path) -> None:
        """Bind the reader to a repository root.

        Args:
            repo_root: The base directory of the repository.
        """
        self.repo_root = repo_root

    def config(self, key: str) -> str | None:
        """Fetch a configuration value from the local git installation.

        Args:
            key: The git configuration key.

        Returns:
            The configured value or null if unset.
        """
        try:
            result = subprocess.run(
                ["git", "config", "--get", key],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return None
        value = result.stdout.strip()
        return value or None
