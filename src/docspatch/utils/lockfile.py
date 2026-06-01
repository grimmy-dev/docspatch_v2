"""Manage file-based locks to prevent concurrent process operations."""

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
    """Hold a repository-level lock for the lifetime of a block.

    Args:
        repo_root: The base repository directory.
    """
    # Cancellation contract: lock is released on any normal exit, exception, or
    # KeyboardInterrupt (finally block). Only SIGKILL can leave a stale lock,
    # and a stale lock is auto-cleared on the next run via _clear_or_fail.
    lock = repo_root / ".docspatch" / "run.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    _acquire(lock)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def _acquire(lock: Path) -> None:
    """Create a lock file, clearing any stale ones found during the attempt.

    Args:
        lock: The path of the lock file to create.
    """
    payload = json.dumps({"pid": os.getpid(), "started": time.time()}).encode()
    for _ in range(2):
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            _clear_or_fail(lock)
            continue
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
        return
    # Second attempt also lost the race: somebody acquired the lock between our
    # clear and re-open. Treat as a live owner so we don't spin.
    _clear_or_fail(lock)


def _clear_or_fail(lock: Path) -> None:
    """Remove a stale lock file or raise an error if the owner process is still active.

    Args:
        lock: The lock file path.

    Raises:
        LockError: A process is actively holding the lock.
    """
    try:
        data = json.loads(lock.read_text())
        pid, started = int(data["pid"]), float(data["started"])
    except OSError, ValueError, KeyError, TypeError:
        console.print("[yellow]⚠ clearing corrupt run.lock[/yellow]")
        lock.unlink(missing_ok=True)
        return
    if _pid_alive(pid):
        raise LockError.run_in_progress(pid, started)
    console.print(f"[yellow]⚠ clearing stale run.lock (PID {pid} not running)[/yellow]")
    lock.unlink(missing_ok=True)


def _pid_alive(pid: int) -> bool:
    """Determine if a process is still running.

    Args:
        pid: Process ID to probe.

    Returns:
        True if the process is active.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
