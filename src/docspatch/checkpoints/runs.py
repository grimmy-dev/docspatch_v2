"""Discover incomplete docs runs for ``--resume``.

A completed run deletes its own checkpoint thread, so whatever threads remain
in ``docs.sqlite`` belong to interrupted runs that can be resumed.
"""

from __future__ import annotations

from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from docspatch.checkpoints.saver import docs_db_path, open_checkpoint_saver
from docspatch.utils.errors import ConfigError


async def list_incomplete_runs(repo_root: Path) -> list[str]:
    """Resumable docs run ids in ``docs.sqlite``, newest first.

    Review and scout threads share the database but are not resumable here, so
    they are skipped. Run ids are timestamp-prefixed, so a reverse sort is age.
    """
    db_path = docs_db_path(repo_root)
    if not db_path.exists():
        return []
    async with open_checkpoint_saver(db_path) as saver:
        return await _collect_resumable(saver)


async def _collect_resumable(saver: AsyncSqliteSaver) -> list[str]:
    """Docs run ids on an already-open saver, newest first."""
    seen: set[str] = set()
    async for tup in saver.alist(None):
        thread_id = tup.config["configurable"]["thread_id"]
        if not thread_id.startswith(("review-", "scout-")):
            seen.add(thread_id)
    return sorted(seen, reverse=True)


def pick_last_run(run_ids: list[str]) -> str:
    """Return the most recent incomplete run id.

    Raises:
        ConfigError: When there is no incomplete run to resume.
    """
    if not run_ids:
        raise ConfigError.no_runs_to_resume()
    return run_ids[0]


async def discard_incomplete_runs(repo_root: Path) -> None:
    """Drop every resumable docs thread so it stops being offered."""
    db_path = docs_db_path(repo_root)
    if not db_path.exists():
        return
    async with open_checkpoint_saver(db_path) as saver:
        for thread_id in await _collect_resumable(saver):
            await saver.adelete_thread(thread_id)
