"""Run manifest: persistence, secret scrubbing, TTL sweep."""

import json
import time
from pathlib import Path

from docspatch.checkpoints.manifest import (
    RUN_MANIFEST_TTL_DAYS,
    RunManifest,
    manifest_path,
    now_iso,
    sweep_run_manifests,
    write_manifest,
)
from docspatch.utils.secrets import register_secret


def make_manifest(run_id: str = "r1") -> RunManifest:
    return RunManifest(
        run_id=run_id,
        command="docs",
        provider="anthropic",
        tier="fast",
        model="claude-haiku-4-5-20251001",
        started_at=now_iso(),
    )


def test_write_creates_json_at_expected_path(tmp_path: Path) -> None:
    m = make_manifest()
    write_manifest(tmp_path, m)
    path = manifest_path(tmp_path, "r1")
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["run_id"] == "r1"
    assert data["command"] == "docs"
    assert data["provider"] == "anthropic"


def test_write_scrubs_registered_secret(tmp_path: Path) -> None:
    register_secret("sk-supersecretkey9999")
    m = make_manifest()
    m.errors.append("LLM failed with key sk-supersecretkey9999 in trace")
    write_manifest(tmp_path, m)
    text = manifest_path(tmp_path, "r1").read_text()
    assert "supersecretkey" not in text
    assert "sk-s" in text  # only first 4 chars retained


def test_write_scrubs_apikey_shape(tmp_path: Path) -> None:
    m = make_manifest()
    m.errors.append("auth failed: AIzaSyD-abcdefghijklmnop123")
    write_manifest(tmp_path, m)
    text = manifest_path(tmp_path, "r1").read_text()
    assert "abcdefghijklmnop" not in text


def test_sweep_deletes_old_manifests(tmp_path: Path) -> None:
    runs_dir = tmp_path / ".docspatch" / "runs"
    runs_dir.mkdir(parents=True)
    old = runs_dir / "old.json"
    fresh = runs_dir / "fresh.json"
    old.write_text("{}")
    fresh.write_text("{}")
    cutoff_secs = (RUN_MANIFEST_TTL_DAYS + 1) * 86400
    import os

    os.utime(old, (time.time() - cutoff_secs, time.time() - cutoff_secs))

    sweep_run_manifests(tmp_path)
    assert not old.exists()
    assert fresh.exists()


def test_sweep_no_runs_dir_is_noop(tmp_path: Path) -> None:
    sweep_run_manifests(tmp_path)  # should not raise


def test_write_is_atomic_overwrite(tmp_path: Path) -> None:
    m = make_manifest()
    write_manifest(tmp_path, m)
    m.exit_status = "success"
    write_manifest(tmp_path, m)
    data = json.loads(manifest_path(tmp_path, "r1").read_text())
    assert data["exit_status"] == "success"
    assert list((tmp_path / ".docspatch" / "runs").glob("*.tmp")) == []
