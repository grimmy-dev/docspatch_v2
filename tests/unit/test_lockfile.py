"""Per-repo run lock: hold, refuse concurrent, clear stale/corrupt."""

import json
import os
from pathlib import Path

import pytest

from docspatch.utils.errors import LockError
from docspatch.utils.lockfile import run_lock


def lock_path(repo_root: Path) -> Path:
    return repo_root / ".docspatch" / "run.lock"


def test_lock_is_held_during_block_and_released_after(tmp_path: Path) -> None:
    with run_lock(tmp_path):
        assert lock_path(tmp_path).exists()
    assert not lock_path(tmp_path).exists()


def test_lock_records_owning_pid(tmp_path: Path) -> None:
    with run_lock(tmp_path):
        data = json.loads(lock_path(tmp_path).read_text())
        assert data["pid"] == os.getpid()
        assert isinstance(data["started"], float)


def test_second_acquire_while_held_raises(tmp_path: Path) -> None:
    with run_lock(tmp_path), pytest.raises(LockError, match="in progress"), run_lock(tmp_path):
        pass


def test_stale_lock_from_dead_pid_is_cleared(tmp_path: Path) -> None:
    lock = lock_path(tmp_path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps({"pid": 999_999, "started": 1.0}))  # PID that does not exist

    with run_lock(tmp_path):
        assert json.loads(lock.read_text())["pid"] == os.getpid()


def test_corrupt_lock_is_cleared(tmp_path: Path) -> None:
    lock = lock_path(tmp_path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("not json at all")

    with run_lock(tmp_path):
        assert json.loads(lock.read_text())["pid"] == os.getpid()


def test_lock_released_on_exception(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError), run_lock(tmp_path):
        raise RuntimeError("boom")
    assert not lock_path(tmp_path).exists()


def test_permission_error_on_pid_check_treats_lock_as_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A PID owned by another user (os.kill -> PermissionError) must not be stolen."""
    lock = lock_path(tmp_path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps({"pid": 4242, "started": 1.0}))

    def denied(_pid: int, _sig: int) -> None:
        raise PermissionError

    monkeypatch.setattr(os, "kill", denied)

    with pytest.raises(LockError, match="in progress"), run_lock(tmp_path):
        pass
