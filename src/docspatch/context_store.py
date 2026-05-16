"""ContextStore deep module — gzip-compressed JSON cache under .docspatch/cache/."""

import gzip
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from docspatch.errors import CacheError
from docspatch.types.source import FileSummary, FunctionMetadata
from docspatch.utils.fs import atomic_write

CACHE_SCHEMA_VERSION = 1


@dataclass
class CacheInfo:
    file_count: int
    total_size_bytes: int
    last_build: datetime | None


class ContextStore:
    """File-summary cache backed by gzip JSON. Hash-based invalidation, no TTL."""

    def __init__(self, repo_root: Path) -> None:
        self._root = repo_root
        self._cache_dir = repo_root / ".docspatch" / "cache"

    def get_summary(self, path: str) -> FileSummary | None:
        """Return cached FileSummary for path, or None if not cached."""
        entry = self._cache_dir / _cache_key(path)
        if not entry.exists():
            return None
        try:
            data = json.loads(gzip.decompress(entry.read_bytes()))
            return _dict_to_summary(data)
        except Exception as e:
            raise CacheError(f"Failed to read cache for {path}", hint=str(e)) from e

    def set_summary(self, path: str, summary: FileSummary) -> None:
        """Write FileSummary to cache, replacing any existing entry for path."""
        entry = self._cache_dir / _cache_key(path)
        data = gzip.compress(json.dumps(_summary_to_dict(summary)).encode())
        try:
            atomic_write(entry, data)
        except Exception as e:
            raise CacheError(f"Failed to write cache for {path}", hint=str(e)) from e

    def prune_by_hash(self, path: str, new_hash: str, old_hash: str) -> None:
        """Remove cache entry for path if its content_hash matches old_hash."""
        existing = self.get_summary(path)
        if existing and existing.content_hash == old_hash and old_hash != new_hash:
            entry = self._cache_dir / _cache_key(path)
            entry.unlink(missing_ok=True)

    def get_structured_context(self, files: list[str]) -> str:
        """Return a structured text context grouped by directory."""
        by_dir: dict[str, list[FileSummary]] = defaultdict(list)
        for path in files:
            summary = self.get_summary(path)
            if summary:
                dir_key = str(Path(path).parent)
                by_dir[dir_key].append(summary)

        lines: list[str] = []
        for directory in sorted(by_dir):
            lines.append(f"# {directory}")
            for summary in sorted(by_dir[directory], key=lambda s: s.path):
                lines.append(f"  {Path(summary.path).name}")
                lines.append(f"    {summary.summary}")
                for fn in summary.functions:
                    lines.append(f"    - {fn.name}")
            lines.append("")
        return "\n".join(lines)

    def ensure_gitignore(self) -> None:
        """Add .docspatch to .gitignore if not already present. Idempotent."""
        gitignore = self._root / ".gitignore"
        entry = ".docspatch"
        if gitignore.exists():
            content = gitignore.read_text()
            if entry in content:
                return
            new_content = content.rstrip("\n") + f"\n{entry}\n"
        else:
            new_content = f"{entry}\n"
        atomic_write(gitignore, new_content)

    def get_cache_info(self) -> CacheInfo:
        """Return file count, total size, and last-build date from cache directory."""
        if not self._cache_dir.exists():
            return CacheInfo(file_count=0, total_size_bytes=0, last_build=None)

        files = [f for f in self._cache_dir.iterdir() if f.suffix == ".gz"]
        if not files:
            return CacheInfo(file_count=0, total_size_bytes=0, last_build=None)

        stats = [f.stat() for f in files]
        total_size = sum(s.st_size for s in stats)
        last_modified = max(s.st_mtime for s in stats)
        return CacheInfo(
            file_count=len(files),
            total_size_bytes=total_size,
            last_build=datetime.fromtimestamp(last_modified),
        )


def _cache_key(path: str) -> str:
    """Deterministic filename for a cache entry."""
    h = hashlib.sha256(path.encode()).hexdigest()[:32]
    return f"{h}.json.gz"


def _summary_to_dict(s: FileSummary) -> dict:
    return {
        "_schema_version": CACHE_SCHEMA_VERSION,
        "path": s.path,
        "summary": s.summary,
        "content_hash": s.content_hash,
        "functions": [
            {"name": fn.name, "signature": fn.signature, "docstring": fn.docstring, "line_start": fn.line_start, "line_end": fn.line_end}
            for fn in s.functions
        ],
    }


def _dict_to_summary(d: dict) -> FileSummary:
    version = d.get("_schema_version", 0)
    if version != CACHE_SCHEMA_VERSION:
        raise CacheError(
            f"Cache schema version mismatch (got v{version}, expected v{CACHE_SCHEMA_VERSION})",
            hint="Run 'dp cleanup' to clear the cache and rebuild.",
        )
    return FileSummary(
        path=d["path"],
        summary=d["summary"],
        content_hash=d.get("content_hash", ""),
        functions=[
            FunctionMetadata(
                name=fn["name"],
                signature=fn["signature"],
                docstring=fn.get("docstring"),
                line_start=fn.get("line_start", 0),
                line_end=fn.get("line_end", 0),
            )
            for fn in d.get("functions", [])
        ],
    )
