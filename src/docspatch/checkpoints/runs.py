"""Execution run tracking, status persistence, and resume lists."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from docspatch.checkpoints.saver import docs_db_path, open_checkpoint_saver
from docspatch.utils.errors import ConfigError
from docspatch.utils.fs import atomic_write
from docspatch.utils.secrets import scrub

RUNS_SUBDIR = "runs"
RUN_SUMMARY_TTL_DAYS = 30


async def list_incomplete_runs(repo_root: Path) -> list[str]:
    """Retrieve identifiers of unfinished documentation runs.

    Args:
        repo_root: Repository base directory.

    Returns:
        Sorted list of run identifiers.
    """
    db_path = docs_db_path(repo_root)
    if not db_path.exists():
        return []
    async with open_checkpoint_saver(db_path) as saver:
        return await _collect_resumable(saver)


async def _collect_resumable(saver: AsyncSqliteSaver) -> list[str]:
    """Extract resumable run identifiers from a saver instance.

    Args:
        saver: The checkpoint saver.

    Returns:
        List of run identifiers.
    """
    seen: set[str] = set()
    async for tup in saver.alist(None):
        thread_id = tup.config["configurable"]["thread_id"]
        if not thread_id.startswith("review-"):
            seen.add(thread_id)
    return sorted(seen, reverse=True)


def pick_last_run(run_ids: list[str]) -> str:
    """Select the most recent incomplete run.

    Args:
        run_ids: List of available run identifiers.

    Returns:
        The chosen run identifier.

    Raises:
        ConfigError: run_ids is empty.
    """
    if not run_ids:
        raise ConfigError.no_runs_to_resume()
    return run_ids[0]


async def discard_incomplete_runs(repo_root: Path) -> None:
    """Delete all pending documentation run state.

    Args:
        repo_root: Repository base directory.
    """
    db_path = docs_db_path(repo_root)
    if not db_path.exists():
        return
    async with open_checkpoint_saver(db_path) as saver:
        for thread_id in await _collect_resumable(saver):
            await saver.adelete_thread(thread_id)


@dataclass
class RunSummary:
    """Durable summary of one pipeline run."""

    run_id: str
    command: str
    provider: str
    tier: str
    model: str
    started_at: str
    ended_at: str = ""
    exit_status: str = "running"
    flags: dict[str, object] = field(default_factory=dict)
    files_scanned: int = 0
    files_documented: list[str] = field(default_factory=list)
    files_skipped: list[str] = field(default_factory=list)
    functions_documented: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_total: float = 0.0
    errors: list[str] = field(default_factory=list)


def run_summary_path(repo_root: Path, run_id: str) -> Path:
    """Locate the summary file for a specific run.

    Args:
        repo_root: Repository base directory.
        run_id: Run identifier.

    Returns:
        Path object.
    """
    return repo_root / ".docspatch" / RUNS_SUBDIR / f"{run_id}.json"


def now_iso() -> str:
    """Return the current UTC timestamp.

    Returns:
        ISO-8601 string.
    """
    return datetime.now(UTC).isoformat()


def write_run_summary(repo_root: Path, summary: RunSummary) -> None:
    """Serialize and store a run summary atomically.

    Args:
        repo_root: Repository base directory.
        summary: Run summary object.
    """
    payload = json.dumps(asdict(summary), indent=2, sort_keys=True)
    # Scrub at write time so any error text/path that slipped a key in is masked.
    atomic_write(run_summary_path(repo_root, summary.run_id), scrub(payload))


def sweep_run_summaries(repo_root: Path, ttl_days: int = RUN_SUMMARY_TTL_DAYS, now: float | None = None) -> None:
    """Remove expired run summaries from the filesystem.

    Args:
        repo_root: Repository base directory.
        ttl_days: Retention period in days.
        now: Optional current timestamp.
    """
    import time

    runs_dir = repo_root / ".docspatch" / RUNS_SUBDIR
    if not runs_dir.exists():
        return
    cutoff = (now or time.time()) - ttl_days * 86400
    for entry in runs_dir.iterdir():
        if entry.suffix == ".json" and entry.stat().st_mtime < cutoff:
            entry.unlink(missing_ok=True)
