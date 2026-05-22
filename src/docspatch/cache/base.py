"""Generic gzip-JSON cache. Per-pipeline caches subclass and supply mapping.

Subclasses define:
- ``SCHEMA_VERSION`` and ``SUBDIR`` class constants.
- ``to_dict(state)`` and ``from_dict(payload)`` for state ↔ JSON mapping.
- ``LABEL`` for human-readable schema-evict messages.

Everything else (paths, atomic write, memoization, schema evict) is handled
here so new caches stay tiny.
"""

import gzip
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from docspatch.cache.keys import cache_key
from docspatch.ui.console import console
from docspatch.utils.errors import CacheError
from docspatch.utils.fs import atomic_write

_HEADER_BYTES = 4


def _pack(payload: dict[str, Any], schema: int) -> bytes:
    """Schema header (4-byte BE) + gzip-JSON payload."""
    return schema.to_bytes(_HEADER_BYTES, "big") + gzip.compress(json.dumps(payload).encode())


def _unpack(raw: bytes, expected_schema: int) -> tuple[dict[str, Any] | None, int]:
    """Inflate ``raw``. Returns ``(payload, version)``; payload ``None`` on mismatch."""
    if len(raw) < _HEADER_BYTES:
        return None, 0
    version = int.from_bytes(raw[:_HEADER_BYTES], "big")
    if version != expected_schema:
        return None, version
    payload: dict[str, Any] = json.loads(gzip.decompress(raw[_HEADER_BYTES:]))
    return payload, version


@dataclass(frozen=True)
class CacheInfo:
    """File count, total size, and most-recent mtime for any cache flavour."""

    file_count: int
    total_size_bytes: int
    last_build: datetime | None


class GzipJSONCache[T](ABC):
    """File-level cache backed by gzipped JSON. Hash-based invalidation, no TTL."""

    SCHEMA_VERSION: ClassVar[int]
    SUBDIR: ClassVar[str]
    LABEL: ClassVar[str] = "cache"

    def __init__(self, repo_root: Path) -> None:
        self.root = repo_root.resolve()
        self.cache_dir = self.root / ".docspatch" / "cache" / self.SUBDIR
        self._memo: dict[str, T | None] = {}
        self._schema_warned = False

    def get(self, path: str) -> T | None:
        """Return cached state for ``path``, or ``None`` if absent or stale."""
        if path in self._memo:
            return self._memo[path]
        entry = self.cache_dir / cache_key(path)
        try:
            raw = entry.read_bytes()
        except FileNotFoundError:
            self._memo[path] = None
            return None
        except OSError as exc:
            raise CacheError.read_failed(path, exc) from exc
        payload, version = _unpack(raw, self.SCHEMA_VERSION)
        if payload is None:
            self.evict_stale(entry, version)
            self._memo[path] = None
            return None
        state = self.from_dict(payload)
        self._memo[path] = state
        return state

    def set(self, path: str, state: T) -> None:
        """Persist ``state`` for ``path``. Replaces any existing entry."""
        entry = self.cache_dir / cache_key(path)
        try:
            atomic_write(entry, _pack(self.to_dict(state), self.SCHEMA_VERSION))
        except OSError as exc:
            raise CacheError.write_failed(path, exc) from exc
        self._memo[path] = state

    def info(self) -> CacheInfo:
        """Return file count, total size, and last-build timestamp."""
        empty = CacheInfo(file_count=0, total_size_bytes=0, last_build=None)
        try:
            files = [f for f in self.cache_dir.iterdir() if f.suffix == ".gz"]
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

    def evict_stale(self, entry: Path, version: int) -> None:
        """Delete a stale entry. Warn once per instance."""
        entry.unlink(missing_ok=True)
        if not self._schema_warned:
            console.print(
                f"[yellow]{self.LABEL} schema changed (v{version} → v{self.SCHEMA_VERSION}). "
                "Stale entries will be re-built on demand.[/yellow]"
            )
            self._schema_warned = True

    @abstractmethod
    def to_dict(self, state: T) -> dict[str, Any]:
        """Serialise ``state`` to a JSON-safe payload (no schema key)."""

    @abstractmethod
    def from_dict(self, payload: dict[str, Any]) -> T:
        """Materialise the cache state from a JSON payload."""
