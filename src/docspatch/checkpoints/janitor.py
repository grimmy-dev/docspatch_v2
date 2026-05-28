"""Sweep stale checkpoint artifacts: legacy spill files. Once-per-day."""

import asyncio
import re
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

from docspatch.checkpoints.manifest import sweep_run_manifests
from docspatch.utils.config import default_store, read_toml

PENDING_TTL_DAYS = 2
SWEEP_INTERVAL_SECS = 24 * 3600
LAST_SWEEP_KEY = "last_janitor_sweep"
PENDING_RE = re.compile(r"^pending-(?P<run_id>\d{8}-\d{6}-[a-f0-9]{6})\.json\.gz$")


def sweep(checkpoint_dir: Path, now: float | None = None) -> None:
    """Delete legacy ``pending-*.json.gz`` files older than TTL."""
    if not checkpoint_dir.exists():
        return
    cutoff = (now or time.time()) - PENDING_TTL_DAYS * 86400
    for entry in checkpoint_dir.iterdir():
        if PENDING_RE.match(entry.name) and entry.stat().st_mtime < cutoff:
            entry.unlink(missing_ok=True)


def vacuum_checkpoints(checkpoint_dir: Path) -> None:
    """Vacuum the checkpoint sqlite. Caller must ensure no saver holds it open."""
    # VACUUM needs an exclusive lock — kept out of the background sweep, which
    # may run while an AsyncSqliteSaver has the db open.
    db_path = checkpoint_dir / "docs.sqlite"
    if db_path.exists():
        with sqlite3.connect(db_path) as conn:
            conn.execute("VACUUM")


def safe_sweep(repo_root: Path) -> None:
    """Run :func:`sweep` + manifest TTL sweep; log any error and swallow it."""
    try:
        sweep(repo_root / ".docspatch" / "checkpoints")
        sweep_run_manifests(repo_root)
    except Exception as exc:  # noqa: BLE001 — janitor must never crash the command
        try:
            log = repo_root / ".docspatch" / "janitor.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("a", encoding="utf-8") as f:
                f.write(f"{datetime.now(UTC).isoformat()} {exc!r}\n")
        except OSError:
            pass


def maybe_sweep(repo_root: Path) -> None:
    """Sweep only if 24h passed since last sweep. Timestamp persists in repo config.toml."""
    store = default_store(repo_root)
    last = int(read_toml(store.repo_path).get(LAST_SWEEP_KEY) or 0)
    now = int(time.time())
    if last and (now - last) < SWEEP_INTERVAL_SECS:
        return
    safe_sweep(repo_root)
    store.write_repo({LAST_SWEEP_KEY: now})


def start_janitor(repo_root: Path) -> asyncio.Task[None]:
    """Fire-and-forget once-per-day sweep. Returns the task for graceful tests."""
    return asyncio.create_task(asyncio.to_thread(maybe_sweep, repo_root))
