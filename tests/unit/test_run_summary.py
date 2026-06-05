"""Run summary: persistence, secret scrubbing, TTL sweep."""

import json
import time
from pathlib import Path

from docspatch.checkpoints.runs import (
    RUN_SUMMARY_TTL_DAYS,
    RunSummary,
    now_iso,
    run_summary_path,
    sweep_run_summaries,
    write_run_summary,
)
from docspatch.utils.secrets import register_secret


def make_summary(run_id: str = "r1") -> RunSummary:
    return RunSummary(
        run_id=run_id,
        command="docs",
        provider="anthropic",
        tier="fast",
        model="claude-haiku-4-5-20251001",
        started_at=now_iso(),
    )


def test_write_creates_json_at_expected_path(tmp_path: Path) -> None:
    s = make_summary()
    write_run_summary(tmp_path, s)
    path = run_summary_path(tmp_path, "r1")
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["run_id"] == "r1"
    assert data["command"] == "docs"
    assert data["provider"] == "anthropic"


def test_write_scrubs_registered_secret(tmp_path: Path) -> None:
    register_secret("sk-supersecretkey9999")
    s = make_summary()
    s.errors.append("LLM failed with key sk-supersecretkey9999 in trace")
    write_run_summary(tmp_path, s)
    text = run_summary_path(tmp_path, "r1").read_text()
    assert "supersecretkey" not in text
    assert "sk-s" in text  # only first 4 chars retained


def test_write_scrubs_apikey_shape(tmp_path: Path) -> None:
    s = make_summary()
    s.errors.append("auth failed: AIzaSyD-abcdefghijklmnop123")
    write_run_summary(tmp_path, s)
    text = run_summary_path(tmp_path, "r1").read_text()
    assert "abcdefghijklmnop" not in text


def test_sweep_deletes_old_summaries(tmp_path: Path) -> None:
    runs_dir = tmp_path / ".docspatch" / "runs"
    runs_dir.mkdir(parents=True)
    old = runs_dir / "old.json"
    fresh = runs_dir / "fresh.json"
    old.write_text("{}")
    fresh.write_text("{}")
    cutoff_secs = (RUN_SUMMARY_TTL_DAYS + 1) * 86400
    import os

    os.utime(old, (time.time() - cutoff_secs, time.time() - cutoff_secs))

    sweep_run_summaries(tmp_path)
    assert not old.exists()
    assert fresh.exists()


def test_sweep_no_runs_dir_is_noop(tmp_path: Path) -> None:
    sweep_run_summaries(tmp_path)  # should not raise


def test_write_is_atomic_overwrite(tmp_path: Path) -> None:
    s = make_summary()
    write_run_summary(tmp_path, s)
    s.exit_status = "success"
    write_run_summary(tmp_path, s)
    data = json.loads(run_summary_path(tmp_path, "r1").read_text())
    assert data["exit_status"] == "success"
    assert list((tmp_path / ".docspatch" / "runs").glob("*.tmp")) == []
