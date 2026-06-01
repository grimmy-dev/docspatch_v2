"""Coordinate scan planning, file partitioning, and context generation for the scout pipeline."""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path

from docspatch.cache import ScoutCache
from docspatch.pipelines.scout.state import FileMiss, ScanPlan
from docspatch.schemas import FileSummary
from docspatch.source import compress, estimate_tokens, file_hash


def partition_paths(paths: Iterable[str], ctx_store: ScoutCache) -> tuple[list[str], list[FileMiss]]:
    """Split paths into cache hits and misses by checking file existence, modification times, and content hashes.

    Args:
        paths: The repository-relative paths to evaluate.
        ctx_store: The cache containing prior scan results.

    Returns:
        A tuple containing a list of hits and a list of FileMiss objects for cache misses.
    """
    hits: list[str] = []
    misses: list[FileMiss] = []
    for path in paths:
        abs_path = ctx_store.root / path
        try:
            st = abs_path.stat()
        except OSError:
            continue
        cached = ctx_store.get(path)
        # Fast-skip: matching size+mtime → assume unchanged, no read/hash/parse.
        if cached and cached.size == st.st_size and cached.mtime_ns == st.st_mtime_ns:
            hits.append(path)
            continue
        try:
            # Read bytes once: hash on bytes, decode for compress — no encode round-trip.
            raw = abs_path.read_bytes()
        except OSError:
            continue
        content_hash = file_hash(raw)
        if cached and cached.content_hash == content_hash:
            # Hash matches but stat drifted; refresh stat so next run fast-skips.
            ctx_store.set(path, replace(cached, size=st.st_size, mtime_ns=st.st_mtime_ns))
            hits.append(path)
            continue
        try:
            source = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        misses.append(FileMiss(path, source, compress(source), content_hash, prior=cached))
    return hits, misses


def plan_uncached(paths: Iterable[str], ctx_store: ScoutCache) -> ScanPlan:
    """Create a ScanPlan for a set of file paths.

    Args:
        paths: The paths to evaluate for scouting.
        ctx_store: The scout cache instance.

    Returns:
        A populated ScanPlan object.
    """
    hits, misses = partition_paths(paths, ctx_store)
    token_estimate = sum(estimate_tokens(m.compressed) for m in misses)
    return ScanPlan(
        uncached=tuple(m.path for m in misses),
        cached=tuple(hits),
        token_estimate=token_estimate,
        misses=tuple(misses),
    )


def build_structured_context(cache: ScoutCache, files: list[str]) -> str:
    """Assemble cached summaries grouped by directory for use in downstream prompts.

    Args:
        cache: The cache containing stored file summaries.
        files: The list of file paths to include.

    Returns:
        A formatted string containing structured summary information.
    """
    by_dir: dict[str, list[FileSummary]] = defaultdict(list)
    for path in files:
        summary = cache.get(path)
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
