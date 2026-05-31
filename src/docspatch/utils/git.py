"""Read-only git queries. Pure data — no console or config knowledge.

Scoped to a repo root; every call is a plain argument-list subprocess (never
``shell=True``). Returns None rather than raising when git is unavailable.
"""

import subprocess
from pathlib import Path


class GitReader:
    """Read-only git access scoped to ``repo_root``."""

    def __init__(self, repo_root: Path) -> None:
        """Bind the reader to a repository root."""
        self.repo_root = repo_root

    def config(self, key: str) -> str | None:
        """Return a git config value, or None if unset or git is unavailable."""
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
