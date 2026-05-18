"""Cache entry serialisation. TypedDict schema is the cache file contract.

Bumping ``CACHE_SCHEMA_VERSION`` triggers silent eviction of older entries on
read — :class:`docspatch.context_store.store.ContextStore` calls
:func:`decode` and acts on the ``None`` return rather than raising.
"""

import hashlib
import json
from typing import TypedDict

from docspatch.types.source import FileSummary, FunctionMetadata

CACHE_SCHEMA_VERSION = 2


class FunctionDict(TypedDict, total=False):
    name: str
    signature: str
    docstring: str | None
    llm_summary: str | None
    line_start: int
    line_end: int


class CachedSummaryDict(TypedDict, total=False):
    _schema_version: int
    path: str
    summary: str
    content_hash: str
    functions: list[FunctionDict]


def cache_key(rel_path: str) -> str:
    """Deterministic filename for a cache entry keyed on a repo-relative path."""
    h = hashlib.sha256(rel_path.encode()).hexdigest()[:32]
    return f"{h}.json.gz"


def encode(summary: FileSummary) -> bytes:
    """Serialise ``summary`` to compressed JSON bytes ready for cache write."""
    import gzip

    payload: CachedSummaryDict = {
        "_schema_version": CACHE_SCHEMA_VERSION,
        "path": summary.path,
        "summary": summary.summary,
        "content_hash": summary.content_hash,
        "functions": [
            {
                "name": fn.name,
                "signature": fn.signature,
                "docstring": fn.docstring,
                "llm_summary": fn.llm_summary,
                "line_start": fn.line_start,
                "line_end": fn.line_end,
            }
            for fn in summary.functions
        ],
    }
    return gzip.compress(json.dumps(payload).encode())


def decode(raw: bytes) -> tuple[FileSummary | None, int]:
    """Deserialise cache bytes. Returns ``(summary, schema_version)``.

    ``summary`` is ``None`` when the on-disk schema does not match
    :data:`CACHE_SCHEMA_VERSION` — the caller evicts the stale entry.
    Raises :class:`OSError` / :class:`json.JSONDecodeError` /
    :class:`gzip.BadGzipFile` on corruption — callers convert to
    :class:`docspatch.utils.errors.CacheError`.
    """
    import gzip

    data: CachedSummaryDict = json.loads(gzip.decompress(raw))
    version = data.get("_schema_version", 0)
    if version != CACHE_SCHEMA_VERSION:
        return None, version
    return _to_summary(data), version


def _to_summary(d: CachedSummaryDict) -> FileSummary:
    return FileSummary(
        path=d.get("path", ""),
        summary=d.get("summary", ""),
        content_hash=d.get("content_hash", ""),
        functions=[
            FunctionMetadata(
                name=fn.get("name", ""),
                signature=fn.get("signature", ""),
                docstring=fn.get("docstring"),
                llm_summary=fn.get("llm_summary"),
                line_start=fn.get("line_start", 0),
                line_end=fn.get("line_end", 0),
            )
            for fn in d.get("functions", [])
        ],
    )
