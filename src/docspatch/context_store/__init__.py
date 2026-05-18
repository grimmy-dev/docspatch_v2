"""Cache facade. Single import point for callers."""

from docspatch.context_store.codec import CACHE_SCHEMA_VERSION, CachedSummaryDict, cache_key, decode, encode
from docspatch.context_store.store import CacheInfo, ContextStore

__all__ = [
    "CACHE_SCHEMA_VERSION",
    "CacheInfo",
    "CachedSummaryDict",
    "ContextStore",
    "cache_key",
    "decode",
    "encode",
]
