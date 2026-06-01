"""Utilities for listing and managing incomplete runs."""

from __future__ import annotations

from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from docspatch.checkpoints.saver import docs_db_path, open_checkpoint_saver
from docspatch.utils.errors import ConfigError


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
        if not thread_id.startswith(("review-", "scout-")):
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
