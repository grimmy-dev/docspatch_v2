"""Manage ignore patterns for filtering files within a repository."""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pathspec

from docspatch.utils.fs import atomic_write

DOCSPATCH_ENTRY = ".docspatch"
DOCSIGNORE_FILE = ".docsignore"
GITIGNORE_ENTRIES = (DOCSPATCH_ENTRY, DOCSIGNORE_FILE)

DEFAULT_PATTERNS: tuple[str, ...] = (
    "tests/",
    "test/",
    "**/tests/",
    "**/test/",
    "**/__pycache__/",
    ".venv/",
    "venv/",
    "env/",
    "build/",
    "dist/",
    "**/*.egg-info/",
    "node_modules/",
    "migrations/",
    "**/migrations/",
    "setup.py",
    "conftest.py",
    "**/conftest.py",
)


def ensure_docspatch_ignored(repo_root: Path) -> None:
    """Add required docspatch files to the repository gitignore if missing.

    Args:
        repo_root: Repository base directory.
    """
    gitignore = repo_root / ".gitignore"
    try:
        content = gitignore.read_text()
    except FileNotFoundError:
        atomic_write(gitignore, "\n".join(GITIGNORE_ENTRIES) + "\n")
        return
    missing = [e for e in GITIGNORE_ENTRIES if e not in content]
    if not missing:
        return
    atomic_write(gitignore, content.rstrip("\n") + "\n" + "\n".join(missing) + "\n")


@dataclass(frozen=True)
class DocsIgnore:
    """Match repo-relative POSIX paths against ``.docsignore`` patterns."""

    spec: pathspec.PathSpec

    @classmethod
    def empty(cls) -> DocsIgnore:
        """Initialize an ignore object that matches nothing."""
        return cls(spec=pathspec.PathSpec.from_lines("gitignore", []))

    @classmethod
    def defaults(cls) -> DocsIgnore:
        """Initialize an ignore object using only built-in default patterns."""
        return cls(spec=pathspec.PathSpec.from_lines("gitignore", DEFAULT_PATTERNS))

    def matches(self, rel_path: str) -> bool:
        """Determine if a file path is ignored.

        Args:
            rel_path: Repository-relative file path.

        Returns:
            True if the path is matched by ignore rules.
        """
        return self.spec.match_file(rel_path)

    def filter(self, rel_paths: Iterable[str]) -> list[str]:
        """Filter a list of paths, returning only those not ignored.

        Args:
            rel_paths: Iterable of file paths.

        Returns:
            The list of non-ignored paths.
        """
        return [p for p in rel_paths if not self.matches(p)]


def load_docsignore(repo_root: Path) -> DocsIgnore:
    """Load ignoring rules from defaults, gitignore, and user-defined docsignore files.

    Args:
        repo_root: Repository base directory.
    """
    gitignore_lines = _read_lines(repo_root / ".gitignore")
    docsignore_lines = _read_lines(repo_root / DOCSIGNORE_FILE)
    merged = [*DEFAULT_PATTERNS, *gitignore_lines, *docsignore_lines]
    return DocsIgnore(spec=pathspec.PathSpec.from_lines("gitignore", merged))


def _read_lines(path: Path) -> list[str]:
    """Read non-empty lines from a file path.

    Args:
        path: File to read.

    Returns:
        A list of strings or an empty list if the file does not exist.
    """
    return path.read_text().splitlines() if path.exists() else []
