"""Unified cache layer. Per-pipeline caches share gzip+JSON+schema envelope."""

from docspatch.cache.docs import DOCS_CACHE_SCHEMA_VERSION, DocsCache, FileDocState, FunctionDocState
from docspatch.cache.scout import SCOUT_CACHE_SCHEMA_VERSION, CacheInfo, ScoutCache

__all__ = [
    "DOCS_CACHE_SCHEMA_VERSION",
    "SCOUT_CACHE_SCHEMA_VERSION",
    "CacheInfo",
    "DocsCache",
    "FileDocState",
    "FunctionDocState",
    "ScoutCache",
]
