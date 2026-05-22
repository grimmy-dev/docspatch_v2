"""Janitor sweeps expired checkpoint artifacts."""

import os
import time
from pathlib import Path

import pytest

from docspatch.checkpoints.janitor import (
    LAST_SWEEP_KEY,
    PENDING_TTL_DAYS,
    maybe_sweep,
    safe_sweep,
    sweep,
)
from docspatch.utils.config import default_store, read_toml


def make_pending(dir: Path, run_id: str, age_days: float) -> Path:
    """Create a pending file with mtime ``age_days`` in the past."""
    dir.mkdir(parents=True, exist_ok=True)
    path = dir / f"pending-{run_id}.json.gz"
    path.write_bytes(b"")
    past = time.time() - age_days * 86400
    os.utime(path, (past, past))
    return path


def checkpoint_dir(repo_root: Path) -> Path:
    return repo_root / ".docspatch" / "checkpoints"


def test_sweep_deletes_old_pending(tmp_path: Path) -> None:
    old = make_pending(checkpoint_dir(tmp_path), "20200101-000000-aaaaaa", age_days=PENDING_TTL_DAYS + 1)
    fresh = make_pending(checkpoint_dir(tmp_path), "20260519-120000-bbbbbb", age_days=0)

    sweep(checkpoint_dir(tmp_path))

    assert not old.exists()
    assert fresh.exists()


def test_sweep_missing_dir_is_noop(tmp_path: Path) -> None:
    sweep(tmp_path / "nope")  # must not raise


def test_sweep_ignores_unrelated_files(tmp_path: Path) -> None:
    dir = checkpoint_dir(tmp_path)
    dir.mkdir(parents=True, exist_ok=True)
    keep = dir / "scratch.log"
    keep.write_bytes(b"")
    os.utime(keep, (time.time() - 365 * 86400, time.time() - 365 * 86400))

    sweep(dir)

    assert keep.exists()


def test_safe_sweep_swallows_errors_and_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk on fire")

    monkeypatch.setattr("docspatch.checkpoints.janitor.sweep", boom)

    safe_sweep(tmp_path)  # must not raise

    assert "disk on fire" in (tmp_path / ".docspatch" / "janitor.log").read_text()


def test_maybe_sweep_skips_when_recent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Second call within 24h is a no-op (timestamp in config gates re-entry)."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))  # isolate global config
    old = make_pending(checkpoint_dir(tmp_path), "20200101-000000-aaaaaa", age_days=PENDING_TTL_DAYS + 1)

    maybe_sweep(tmp_path)
    assert not old.exists()

    old2 = make_pending(checkpoint_dir(tmp_path), "20200101-000000-cccccc", age_days=PENDING_TTL_DAYS + 1)
    maybe_sweep(tmp_path)
    assert old2.exists()  # gate held


def test_maybe_sweep_runs_after_24h(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A stale config timestamp lets the sweep run again."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    store = default_store(tmp_path)
    store.write_repo({LAST_SWEEP_KEY: int(time.time()) - 25 * 3600})

    old = make_pending(checkpoint_dir(tmp_path), "20200101-000000-aaaaaa", age_days=PENDING_TTL_DAYS + 1)
    maybe_sweep(tmp_path)

    assert not old.exists()


def test_maybe_sweep_persists_timestamp_in_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No extra marker file; timestamp lives in repo config.toml."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    maybe_sweep(tmp_path)

    config = tmp_path / ".docspatch" / "config.toml"
    assert LAST_SWEEP_KEY in read_toml(config)
    assert not (tmp_path / ".docspatch" / "checkpoints" / ".janitor_last").exists()
