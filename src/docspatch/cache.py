"""Disk-backed Gzip-JSON cache for storing per-function documentation state."""

import gzip
import hashlib
import json
import os
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from docspatch.schemas import FunctionDocState
from docspatch.ui.console import console
from docspatch.utils.errors import CacheError
from docspatch.utils.fs import atomic_write

__all__ = [
    "DOCS_CACHE_SCHEMA_VERSION",
    "CacheInfo",
    "DocsCache",
    "FileDocState",
    "FunctionDocState",
    "GzipJSONCache",
    "cache_key",
]

# ---- Key derivation --------------------------------------------------------

KEY_HEX_WIDTH = 32


def cache_key(rel_path: str, suffix: str = ".json.gz") -> str:
    """Compute a deterministic filename for a path. Stable across repository moves.

    Args:
        rel_path: Relative file path to key.
        suffix: File extension for the cached entry.

    Returns:
        The 32-character SHA-256 hash.
    """
    digest = hashlib.sha256(rel_path.encode()).hexdigest()[:KEY_HEX_WIDTH]
    return f"{digest}{suffix}"


# ---- Gzip-JSON envelope ----------------------------------------------------

_HEADER_BYTES = 4


def _pack(payload: dict[str, Any], schema: int) -> bytes:
    """Prefix a JSON payload with a schema version header and compress it.

    Args:
        payload: Dictionary to serialize.
        schema: Integer schema version.

    Returns:
        Packed bytes.
    """
    return schema.to_bytes(_HEADER_BYTES, "big") + gzip.compress(json.dumps(payload).encode())


def _unpack(raw: bytes, expected_schema: int) -> tuple[dict[str, Any] | None, int]:
    """Inflate binary cache data and validate the schema version.

    Args:
        raw: Binary data read from disk.
        expected_schema: Version required for parsing.

    Returns:
        A tuple of the payload dict and the schema version.
    """
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


# ---- Generic base ----------------------------------------------------------


class GzipJSONCache[T](ABC):
    """File-level cache backed by gzipped JSON. Hash-based invalidation, no TTL."""

    SCHEMA_VERSION: ClassVar[int]
    SUBDIR: ClassVar[str]
    LABEL: ClassVar[str] = "cache"

    def __init__(self, repo_root: Path) -> None:
        """Initialize the cache with a specified repository root path.

        Args:
            repo_root: The file system path to the root of the repository.
        """
        self.root = repo_root.resolve()
        self.cache_dir = self.root / ".docspatch" / "cache" / self.SUBDIR
        self._memo: dict[str, T | None] = {}
        self._schema_warned = False

    def get(self, path: str) -> T | None:
        """Fetch and decode cached state for a given path.

        Args:
            path: Relative path to retrieve.

        Returns:
            Deserialized object or None if missing, corrupted, or stale.

        Raises:
            CacheError: Reading the file fails.
        """
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
        try:
            payload, version = _unpack(raw, self.SCHEMA_VERSION)
            state = self.from_dict(payload) if payload is not None else None
        except (OSError, EOFError, ValueError, UnicodeDecodeError, KeyError, TypeError) as exc:
            # Corrupt entry (bad gzip, truncated, unparseable JSON, bad shape):
            # evict and report a miss so the pipeline rebuilds it.
            self.evict_corrupt(entry, exc)
            self._memo[path] = None
            return None
        if state is None:
            self.evict_stale(entry, version)
            self._memo[path] = None
            return None
        self._memo[path] = state
        return state

    def set(self, path: str, state: T) -> None:
        """Atomically write the state to disk for a given path.

        Args:
            path: Relative path to store.
            state: Object to persist.

        Raises:
            CacheError: Writing the file fails.
        """
        entry = self.cache_dir / cache_key(path)
        try:
            atomic_write(entry, _pack(self.to_dict(state), self.SCHEMA_VERSION))
        except OSError as exc:
            raise CacheError.write_failed(path, exc) from exc
        self._memo[path] = state

    def delete(self, path: str) -> None:
        """Remove the cached entry for a path.

        Args:
            path: Relative path to remove.
        """
        entry = self.cache_dir / cache_key(path)
        entry.unlink(missing_ok=True)
        self._memo[path] = None

    def info(self) -> CacheInfo:
        """Retrieve file count, total size, and the last-modified timestamp.

        Returns:
            Cache statistics object.
        """
        empty = CacheInfo(file_count=0, total_size_bytes=0, last_build=None)
        try:
            with os.scandir(self.cache_dir) as it:
                stats = [e.stat() for e in it if e.name.endswith(".gz")]
        except FileNotFoundError:
            return empty
        if not stats:
            return empty
        return CacheInfo(
            file_count=len(stats),
            total_size_bytes=sum(s.st_size for s in stats),
            last_build=datetime.fromtimestamp(max(s.st_mtime for s in stats)),
        )

    def evict_stale(self, entry: Path, version: int) -> None:
        """Remove an entry due to a schema mismatch.

        Args:
            entry: Path to the stale file.
            version: The detected stale version.
        """
        entry.unlink(missing_ok=True)
        if not self._schema_warned:
            console.print(
                f"[yellow]{self.LABEL} schema changed (v{version} → v{self.SCHEMA_VERSION}). "
                "Stale entries will be re-built on demand.[/yellow]"
            )
            self._schema_warned = True

    def evict_corrupt(self, entry: Path, exc: Exception) -> None:
        """Remove an entry that failed deserialization.

        Args:
            entry: Path to the broken file.
            exc: The exception triggering eviction.
        """
        entry.unlink(missing_ok=True)
        console.print(f"[yellow]{self.LABEL}: corrupt entry evicted ({exc}). It will be re-built.[/yellow]")

    @abstractmethod
    def to_dict(self, state: T) -> dict[str, Any]:
        """Serialize state to a JSON-compatible dictionary.

        Args:
            state: Object to serialize.

        Returns:
            Serialized payload dictionary.
        """

    @abstractmethod
    def from_dict(self, payload: dict[str, Any]) -> T:
        """Create an object instance from a dictionary.

        Args:
            payload: Deserialized JSON data.

        Returns:
            Reconstructed state object.
        """


# ---- Docs cache ------------------------------------------------------------

DOCS_CACHE_SCHEMA_VERSION = 1


@dataclass
class FileDocState:
    """File-level state: file hash and per-function map keyed by qualname."""

    path: str
    file_hash: str
    functions: dict[str, FunctionDocState] = field(default_factory=dict)
    # size + mtime_ns power constant-time fast-skip before any read/parse.
    size: int = 0
    mtime_ns: int = 0


class DocsCache(GzipJSONCache[FileDocState]):
    """Docs pipeline's per-function generation state."""

    SCHEMA_VERSION = DOCS_CACHE_SCHEMA_VERSION
    SUBDIR = "docs"
    LABEL = "Docs cache"

    def to_dict(self, state: FileDocState) -> dict[str, Any]:
        """Convert file documentation state to a dictionary.

        Args:
            state: The documentation state object.

        Returns:
            A dictionary representation of the state.
        """
        return asdict(state)

    def from_dict(self, payload: dict[str, Any]) -> FileDocState:
        """Create a FileDocState from raw dictionary data.

        Args:
            payload: The dictionary containing state fields.

        Returns:
            A FileDocState instance.
        """
        return FileDocState(
            path=payload.get("path", ""),
            file_hash=payload.get("file_hash", ""),
            functions={name: FunctionDocState(**fn) for name, fn in payload.get("functions", {}).items()},
            size=payload.get("size", 0),
            mtime_ns=payload.get("mtime_ns", 0),
        )

    def needs_rerun(self, path: str, current: dict[str, FunctionDocState]) -> list[str]:
        """Identify functions requiring documentation updates.

        Args:
            path: File path to check.
            current: Current function states from the file.

        Returns:
            A list of function qualified names.
        """
        cached = self.get(path)
        if cached is None:
            return list(current)
        targets: list[str] = []
        for qualname, fn in current.items():
            prior = cached.functions.get(qualname)
            if prior is None or prior.hash != fn.hash or not prior.has_docstring:
                targets.append(qualname)
        return targets
