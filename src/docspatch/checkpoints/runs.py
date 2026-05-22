"""Discover incomplete docs runs for ``--resume``.

A completed run deletes its own checkpoint thread, so whatever threads remain
in ``docs.sqlite`` belong to interrupted runs that can be resumed.
"""

from __future__ import annotations

from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from docspatch.utils.errors import ConfigError


async def list_incomplete_runs(repo_root: Path) -> list[str]:
    """Resumable docs run ids in ``docs.sqlite``, newest first.

    Review and scout threads share the database but are not resumable here, so
    they are skipped. Run ids are timestamp-prefixed, so a reverse sort is age.
    """
    db_path = repo_root / ".docspatch" / "checkpoints" / "docs.sqlite"
    if not db_path.exists():
        return []
    seen: set[str] = set()
    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as saver:
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
        raise ConfigError(
            "No incomplete runs to resume.",
            hint="Start a fresh run with `dp docs`.",
        )
    return run_ids[0]
