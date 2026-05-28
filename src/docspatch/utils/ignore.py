"""Ignore helpers: ``.gitignore`` additions and ``.docsignore`` matching."""

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
    """Add ``.docspatch`` and ``.docsignore`` to the repo's ``.gitignore`` if absent."""
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
        """Match nothing."""
        return cls(spec=pathspec.PathSpec.from_lines("gitignore", []))

    @classmethod
    def defaults(cls) -> DocsIgnore:
        """Match the built-in default patterns only."""
        return cls(spec=pathspec.PathSpec.from_lines("gitignore", DEFAULT_PATTERNS))

    def matches(self, rel_path: str) -> bool:
        """True if ``rel_path`` is ignored."""
        return self.spec.match_file(rel_path)

    def filter(self, rel_paths: Iterable[str]) -> list[str]:
        """Return only the paths not matched."""
        return [p for p in rel_paths if not self.matches(p)]


def load_docsignore(repo_root: Path) -> DocsIgnore:
    """Built-in defaults + repo ``.gitignore`` + user ``.docsignore`` (whichever exist)."""
    gitignore_lines = _read_lines(repo_root / ".gitignore")
    docsignore_lines = _read_lines(repo_root / DOCSIGNORE_FILE)
    merged = [*DEFAULT_PATTERNS, *gitignore_lines, *docsignore_lines]
    return DocsIgnore(spec=pathspec.PathSpec.from_lines("gitignore", merged))


def _read_lines(path: Path) -> list[str]:
    """Read lines from ``path``; empty list when missing."""
    return path.read_text().splitlines() if path.exists() else []
