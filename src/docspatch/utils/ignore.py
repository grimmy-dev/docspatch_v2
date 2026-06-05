"""Contains ignore-rule definitions and file matching utilities based on pathspec patterns."""

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
    """Append required docspatch entries to the repository gitignore file.

    Args:
        repo_root: Base path of the repository.
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
        """Create an empty ignore instance that matches no file paths.

        Returns:
            A DocsIgnore instance with no active rules.
        """
        return cls(spec=pathspec.PathSpec.from_lines("gitignore", []))

    @classmethod
    def defaults(cls) -> DocsIgnore:
        """Create an ignore instance using only the built-in path patterns.

        Returns:
            A DocsIgnore instance configured with default ignore rules.
        """
        return cls(spec=pathspec.PathSpec.from_lines("gitignore", DEFAULT_PATTERNS))

    def matches(self, rel_path: str) -> bool:
        """Check if a repository-relative path matches any configured ignore pattern.

        Args:
            rel_path: Posix-style file path relative to the repository root.

        Returns:
            True if the path is matched by the ignore patterns.
        """
        return self.spec.match_file(rel_path)

    def filter(self, rel_paths: Iterable[str]) -> list[str]:
        """Exclude matched paths from an iterable of repository-relative file paths.

        Args:
            rel_paths: Collection of relative file paths to evaluate.

        Returns:
            A list of file paths that do not match the ignore rules.
        """
        return [p for p in rel_paths if not self.matches(p)]


def load_docsignore(repo_root: Path) -> DocsIgnore:
    """Merge default, gitignore, and docsignore patterns into a single ignore spec.

    Args:
        repo_root: Root directory of the repository.

    Returns:
        A combined DocsIgnore pattern matcher.
    """
    gitignore_lines = _read_lines(repo_root / ".gitignore")
    docsignore_lines = _read_lines(repo_root / DOCSIGNORE_FILE)
    merged = [*DEFAULT_PATTERNS, *gitignore_lines, *docsignore_lines]
    return DocsIgnore(spec=pathspec.PathSpec.from_lines("gitignore", merged))


def _read_lines(path: Path) -> list[str]:
    """Read all file lines from the given path if it exists.

    Args:
        path: Location of the file to load.

    Returns:
        List of lines in the file, or an empty list if missing.
    """
    return path.read_text().splitlines() if path.exists() else []
