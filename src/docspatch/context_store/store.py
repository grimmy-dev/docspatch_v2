"""ContextStore — gzip-compressed JSON cache under ``.docspatch/cache/``.

Design notes:
- Cache keys hash against paths **relative to** ``repo_root`` so a repo move
  or CI checkout under a different absolute path does not invalidate the cache.
- Schema mismatches auto-evict (delete + warn) instead of raising — bumps must
  be silently survivable so users never hit a hard wall after ``dp`` updates.
- An in-memory dict memoises decoded summaries within a single instance so
  repeated reads (estimate scan, structured context render) skip gzip + JSON.
"""

import gzip
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from docspatch.context_store.codec import CACHE_SCHEMA_VERSION, cache_key, decode, encode
from docspatch.types.source import FileSummary
from docspatch.ui.console import console
from docspatch.utils.errors import CacheError
from docspatch.utils.fs import atomic_write


@dataclass(frozen=True)
class CacheInfo:
    file_count: int
    total_size_bytes: int
    last_build: datetime | None


class ContextStore:
    """File-summary cache backed by gzip JSON. Hash-based invalidation, no TTL.

    Paths are treated as opaque cache keys. Callers are expected to pass
    repo-relative POSIX strings (the convention used by :class:`GitReader`)
    so cache entries survive repo moves and CI checkouts under different
    absolute paths.
    """

    def __init__(self, repo_root: Path) -> None:
        self.root = repo_root.resolve()
        self._cache_dir = self.root / ".docspatch" / "cache"
        self._memo: dict[str, FileSummary | None] = {}
        self._schema_warned = False

    def get_summary(self, path: str) -> FileSummary | None:
        """Return cached :class:`FileSummary` for ``path``, or ``None`` if absent / stale."""
        if path in self._memo:
            return self._memo[path]

        entry = self._cache_dir / cache_key(path)
        try:
            raw = entry.read_bytes()
        except FileNotFoundError:
            self._memo[path] = None
            return None

        try:
            summary, version = decode(raw)
        except (OSError, json.JSONDecodeError, gzip.BadGzipFile) as exc:
            raise CacheError.read_failed(path, exc) from exc

        if summary is None:
            self._evict_stale(entry, version)
            self._memo[path] = None
            return None

        self._memo[path] = summary
        return summary

    def set_summary(self, path: str, summary: FileSummary) -> None:
        """Write ``summary`` to cache, replacing any existing entry for ``path``."""
        entry = self._cache_dir / cache_key(path)
        try:
            atomic_write(entry, encode(summary))
        except OSError as exc:
            raise CacheError.write_failed(path, exc) from exc
        self._memo[path] = summary

    def get_structured_context(self, files: list[str]) -> str:
        """Return a structured text context grouped by directory."""
        by_dir: dict[str, list[FileSummary]] = defaultdict(list)
        for path in files:
            summary = self.get_summary(path)
            if summary:
                by_dir[str(Path(path).parent)].append(summary)

        lines: list[str] = []
        for directory in sorted(by_dir):
            lines.append(f"# {directory}")
            for summary in sorted(by_dir[directory], key=lambda s: s.path):
                lines.append(f"  {Path(summary.path).name}")
                lines.append(f"    {summary.summary}")
                for fn in summary.functions:
                    note = fn.llm_summary or fn.docstring
                    suffix = f" — {note.splitlines()[0]}" if note else ""
                    lines.append(f"    - {fn.name}{suffix}")
            lines.append("")
        return "\n".join(lines)

    def ensure_gitignore(self) -> None:
        """Add ``.docspatch`` to .gitignore if not already present. Idempotent."""
        gitignore = self.root / ".gitignore"
        entry = ".docspatch"
        try:
            content = gitignore.read_text()
        except FileNotFoundError:
            atomic_write(gitignore, f"{entry}\n")
            return
        if entry in content:
            return
        atomic_write(gitignore, content.rstrip("\n") + f"\n{entry}\n")

    def get_cache_info(self) -> CacheInfo:
        """Return file count, total size, and last-build date from the cache directory."""
        empty = CacheInfo(file_count=0, total_size_bytes=0, last_build=None)
        try:
            files = [f for f in self._cache_dir.iterdir() if f.suffix == ".gz"]
        except FileNotFoundError:
            return empty
        if not files:
            return empty

        stats = [f.stat() for f in files]
        return CacheInfo(
            file_count=len(files),
            total_size_bytes=sum(s.st_size for s in stats),
            last_build=datetime.fromtimestamp(max(s.st_mtime for s in stats)),
        )

    def _evict_stale(self, entry: Path, version: int) -> None:
        entry.unlink(missing_ok=True)
        if not self._schema_warned:
            console.print(
                f"[yellow]Cache schema changed (v{version} → v{CACHE_SCHEMA_VERSION}). Old entries will be re-scouted on demand.[/yellow]"
            )
            self._schema_warned = True
