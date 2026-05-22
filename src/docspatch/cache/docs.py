"""DocsCache — per-file docstring-generation idempotency state."""

from dataclasses import asdict, dataclass, field
from typing import Any

from docspatch.cache.base import GzipJSONCache

DOCS_CACHE_SCHEMA_VERSION = 1

__all__ = ["DOCS_CACHE_SCHEMA_VERSION", "DocsCache", "FileDocState", "FunctionDocState"]


@dataclass
class FunctionDocState:
    """Hash + presence flag for a single function."""

    hash: str
    has_docstring: bool
    line_start: int = 0


@dataclass
class FileDocState:
    """File-level state: file hash and per-function map keyed by qualname."""

    path: str
    file_hash: str
    functions: dict[str, FunctionDocState] = field(default_factory=dict)


class DocsCache(GzipJSONCache[FileDocState]):
    """Docs pipeline's per-function generation state."""

    SCHEMA_VERSION = DOCS_CACHE_SCHEMA_VERSION
    SUBDIR = "docs"
    LABEL = "Docs cache"

    def to_dict(self, state: FileDocState) -> dict[str, Any]:
        return asdict(state)

    def from_dict(self, payload: dict[str, Any]) -> FileDocState:
        return FileDocState(
            path=payload.get("path", ""),
            file_hash=payload.get("file_hash", ""),
            functions={name: FunctionDocState(**fn) for name, fn in payload.get("functions", {}).items()},
        )

    def needs_rerun(self, path: str, current: dict[str, FunctionDocState]) -> list[str]:
        """Return qualnames in ``current`` that should be (re)generated."""
        cached = self.get(path)
        if cached is None:
            return list(current)
        targets: list[str] = []
        for qualname, fn in current.items():
            prior = cached.functions.get(qualname)
            if prior is None or prior.hash != fn.hash or not prior.has_docstring:
                targets.append(qualname)
        return targets

    # Back-compat aliases: existing callers use ``get_state`` / ``set_state``.
    def get_state(self, path: str) -> FileDocState | None:
        return self.get(path)

    def set_state(self, path: str, state: FileDocState) -> None:
        self.set(path, state)
