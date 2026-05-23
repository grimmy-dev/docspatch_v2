"""Cancellation contract: atomic_write, run_lock, no orphan asyncio tasks."""

import asyncio
import json
import os
import signal
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from docspatch.utils.fs import atomic_write
from docspatch.utils.lockfile import run_lock


def test_atomic_write_keyboardinterrupt_leaves_original_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "out.txt"
    target.write_text("original")

    real_write_text = Path.write_text

    def interrupt_during_tmp_write(self: Path, *args: object, **kwargs: object) -> int:
        if self.suffix == ".tmp":
            raise KeyboardInterrupt
        return real_write_text(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "write_text", interrupt_during_tmp_write)

    with pytest.raises(KeyboardInterrupt):
        atomic_write(target, "new content")

    assert target.read_text() == "original"
    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_write_oserror_leaves_original_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "out.txt"
    target.write_text("original")

    def boom(self: Path, *_a: object, **_k: object) -> int:
        if self.suffix == ".tmp":
            raise OSError("disk full")
        return 0

    monkeypatch.setattr(Path, "write_text", boom)

    with pytest.raises(OSError, match="disk full"):
        atomic_write(target, "new content")

    assert target.read_text() == "original"
    assert list(tmp_path.glob("*.tmp")) == []


def test_run_lock_released_on_keyboardinterrupt(tmp_path: Path) -> None:
    lock = tmp_path / ".docspatch" / "run.lock"
    with pytest.raises(KeyboardInterrupt), run_lock(tmp_path):
        assert lock.exists()
        raise KeyboardInterrupt
    assert not lock.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only SIGINT semantics")
def test_run_lock_released_after_sigint_subprocess(tmp_path: Path) -> None:
    """End-to-end: SIGINT to a child holding the lock → lock cleared on exit."""
    script = textwrap.dedent(
        f"""
        import json, os, time
        from pathlib import Path
        from docspatch.utils.lockfile import run_lock
        repo = Path({str(tmp_path)!r})
        with run_lock(repo):
            (repo / ".docspatch" / "ready").write_text(str(os.getpid()))
            time.sleep(30)
        """
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        env={**os.environ},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    ready = tmp_path / ".docspatch" / "ready"
    deadline = 5.0
    waited = 0.0
    while not ready.exists() and waited < deadline:
        if proc.poll() is not None:
            stdout, stderr = proc.communicate()
            pytest.fail(f"child exited early: {stderr.decode()}")
        import time as _t

        _t.sleep(0.05)
        waited += 0.05
    assert ready.exists(), "child never acquired lock"

    proc.send_signal(signal.SIGINT)
    proc.wait(timeout=5)

    assert not (tmp_path / ".docspatch" / "run.lock").exists()


def test_no_orphan_tasks_after_asyncio_run() -> None:
    """Every task started inside asyncio.run is finished or cancelled by exit."""
    captured: list[asyncio.Task[None]] = []

    async def child() -> None:
        await asyncio.sleep(1.0)

    async def main() -> None:
        captured.append(asyncio.create_task(child()))
        await asyncio.sleep(0.01)
        raise RuntimeError("simulated interrupt")

    with pytest.raises(RuntimeError):
        asyncio.run(main())

    assert captured, "test bug: no task captured"
    # asyncio.run cancels pending tasks during shutdown; the loop is closed.
    assert captured[0].done()
    assert captured[0].cancelled() or captured[0].exception() is not None


def test_lock_file_payload_after_acquire(tmp_path: Path) -> None:
    with run_lock(tmp_path):
        payload = json.loads((tmp_path / ".docspatch" / "run.lock").read_text())
    assert payload["pid"] == os.getpid()
