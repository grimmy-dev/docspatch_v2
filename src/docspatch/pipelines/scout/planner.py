"""Cache-aware planning. Decides which files need scouting and the prompt cost."""

from collections.abc import Iterable

from docspatch.context_store import ContextStore
from docspatch.pipelines.scout.types import FileMiss, ScanPlan
from docspatch.utils.sourcer import Sourcer


def partition_paths(paths: Iterable[str], ctx_store: ContextStore) -> tuple[list[str], list[FileMiss]]:
    """Split ``paths`` into cache hits (path only) and misses (with source+hash).

    Paths are repo-relative POSIX strings (the convention used by
    :class:`GitReader`). Source is read via ``ctx_store.root / path``.
    Files unreadable on disk are silently skipped — same policy as the scout
    runner, since they cannot be summarised either way.
    """
    hits: list[str] = []
    misses: list[FileMiss] = []
    for path in paths:
        try:
            source = (ctx_store.root / path).read_text(encoding="utf-8")
        except OSError:
            continue
        content_hash = Sourcer.hash(source)
        cached = ctx_store.get_summary(path)
        if cached and cached.content_hash == content_hash:
            hits.append(path)
        else:
            misses.append(FileMiss(path, source, Sourcer.compress(source), content_hash))
    return hits, misses


def plan_uncached(paths: Iterable[str], ctx_store: ContextStore) -> ScanPlan:
    """Build a :class:`ScanPlan` for ``paths`` against the current cache.

    Token estimate covers uncached files only — cached entries are skipped by
    the runner and must not show up in cost projections.
    """
    hits, misses = partition_paths(paths, ctx_store)
    token_estimate = sum(Sourcer.estimate_tokens(m.compressed) for m in misses)
    return ScanPlan(
        uncached=tuple(m.path for m in misses),
        cached=tuple(hits),
        token_estimate=token_estimate,
    )
