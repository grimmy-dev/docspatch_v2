"""Cache-aware planning: which files need scouting, and at what token cost."""

from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

from docspatch.cache import ScoutCache
from docspatch.pipelines.scout.state import FileMiss, ScanPlan
from docspatch.source import compress, estimate_tokens, file_hash
from docspatch.types.source import FileSummary


def partition_paths(paths: Iterable[str], ctx_store: ScoutCache) -> tuple[list[str], list[FileMiss]]:
    """Split ``paths`` into cache hits (path only) and misses (with source + hash).

    Paths are repo-relative POSIX strings; source is read via ``ctx_store.root``.
    Files unreadable on disk are skipped — they cannot be summarised anyway.
    """
    hits: list[str] = []
    misses: list[FileMiss] = []
    for path in paths:
        try:
            source = (ctx_store.root / path).read_text(encoding="utf-8")
        except OSError:
            continue
        content_hash = file_hash(source)
        cached = ctx_store.get(path)
        if cached and cached.content_hash == content_hash:
            hits.append(path)
        else:
            misses.append(FileMiss(path, source, compress(source), content_hash))
    return hits, misses


def plan_uncached(paths: Iterable[str], ctx_store: ScoutCache) -> ScanPlan:
    """Build a :class:`ScanPlan` for ``paths``. Token estimate covers misses only."""
    hits, misses = partition_paths(paths, ctx_store)
    token_estimate = sum(estimate_tokens(m.compressed) for m in misses)
    return ScanPlan(
        uncached=tuple(m.path for m in misses),
        cached=tuple(hits),
        token_estimate=token_estimate,
    )


def build_structured_context(cache: ScoutCache, files: list[str]) -> str:
    """Render cached scout summaries grouped by directory for downstream prompts."""
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
