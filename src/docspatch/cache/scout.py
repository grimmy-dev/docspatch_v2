"""ScoutCache — per-file LLM summary cache. Was ``ContextStore`` storage."""

from typing import Any

from docspatch.cache.base import CacheInfo, GzipJSONCache
from docspatch.types.source import FileSummary, FunctionMetadata

SCOUT_CACHE_SCHEMA_VERSION = 2

__all__ = ["SCOUT_CACHE_SCHEMA_VERSION", "CacheInfo", "ScoutCache"]


class ScoutCache(GzipJSONCache[FileSummary]):
    """Scout pipeline's file-summary cache. Hash-keyed, schema-versioned."""

    SCHEMA_VERSION = SCOUT_CACHE_SCHEMA_VERSION
    SUBDIR = "scout"
    LABEL = "Scout cache"

    def to_dict(self, state: FileSummary) -> dict[str, Any]:
        return {
            "path": state.path,
            "summary": state.summary,
            "content_hash": state.content_hash,
            "functions": [
                {
                    "name": fn.name,
                    "signature": fn.signature,
                    "docstring": fn.docstring,
                    "llm_summary": fn.llm_summary,
                    "line_start": fn.line_start,
                    "line_end": fn.line_end,
                }
                for fn in state.functions
            ],
        }

    def from_dict(self, payload: dict[str, Any]) -> FileSummary:
        return FileSummary(
            path=payload.get("path", ""),
            summary=payload.get("summary", ""),
            content_hash=payload.get("content_hash", ""),
            functions=[
                FunctionMetadata(
                    name=fn.get("name", ""),
                    signature=fn.get("signature", ""),
                    docstring=fn.get("docstring"),
                    llm_summary=fn.get("llm_summary"),
                    line_start=fn.get("line_start", 0),
                    line_end=fn.get("line_end", 0),
                )
                for fn in payload.get("functions", [])
            ],
        )
