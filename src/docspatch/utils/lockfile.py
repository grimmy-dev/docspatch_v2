"""Per-repo run lock — refuses a second ``dp docs`` on the same repository.

The lock is a small JSON file at ``.docspatch/run.lock`` holding the owning
PID and start time. A lock left by a dead process is treated as stale and
cleared automatically.
"""

import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from docspatch.ui import console
from docspatch.utils.errors import LockError


@contextmanager
def run_lock(repo_root: Path) -> Iterator[None]:
    """Hold the per-repo run lock for the duration of the block."""
    # Cancellation contract: lock is released on any normal exit, exception, or
    # KeyboardInterrupt (finally block). Only SIGKILL can leave a stale lock,
    # and a stale lock is auto-cleared on the next run via _clear_or_fail.
    lock = repo_root / ".docspatch" / "run.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    if lock.exists():
        _clear_or_fail(lock)
    lock.write_text(json.dumps({"pid": os.getpid(), "started": time.time()}))
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def _clear_or_fail(lock: Path) -> None:
    """Clear a stale or corrupt lock; raise when a live process still owns it."""
    try:
        data = json.loads(lock.read_text())
        pid, started = int(data["pid"]), float(data["started"])
    except (OSError, ValueError, KeyError, TypeError):
        console.print("[yellow]⚠ clearing corrupt run.lock[/yellow]")
        lock.unlink(missing_ok=True)
        return
    if _pid_alive(pid):
        raise LockError.run_in_progress(pid, started)
    console.print(f"[yellow]⚠ clearing stale run.lock (PID {pid} not running)[/yellow]")
    lock.unlink(missing_ok=True)


def _pid_alive(pid: int) -> bool:
    """True if a process with ``pid`` exists. Signal 0 probes without delivering."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
