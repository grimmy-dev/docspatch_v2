"""Persistent per-run audit record at ``.docspatch/runs/<run_id>.json``."""

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from docspatch.utils.fs import atomic_write
from docspatch.utils.secrets import scrub

RUNS_SUBDIR = "runs"
RUN_MANIFEST_TTL_DAYS = 30


@dataclass
class RunManifest:
    """Durable summary of one pipeline run."""

    run_id: str
    command: str
    provider: str
    tier: str
    model: str
    started_at: str
    ended_at: str = ""
    exit_status: str = "running"
    flags: dict[str, object] = field(default_factory=dict)
    files_scanned: int = 0
    files_documented: list[str] = field(default_factory=list)
    files_skipped: list[str] = field(default_factory=list)
    functions_documented: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_total: float = 0.0
    errors: list[str] = field(default_factory=list)


def manifest_path(repo_root: Path, run_id: str) -> Path:
    """Path to the manifest file for ``run_id``."""
    return repo_root / ".docspatch" / RUNS_SUBDIR / f"{run_id}.json"


def now_iso() -> str:
    """Current UTC time in ISO-8601."""
    return datetime.now(UTC).isoformat()


def write_manifest(repo_root: Path, manifest: RunManifest) -> None:
    """Persist ``manifest`` atomically. Secrets are scrubbed from every string."""
    payload = json.dumps(asdict(manifest), indent=2, sort_keys=True)
    # Scrub at write time so any error text/path that slipped a key in is masked.
    atomic_write(manifest_path(repo_root, manifest.run_id), scrub(payload))


def sweep_run_manifests(
    repo_root: Path, ttl_days: int = RUN_MANIFEST_TTL_DAYS, now: float | None = None
) -> None:
    """Delete manifests older than ``ttl_days``."""
    import time

    runs_dir = repo_root / ".docspatch" / RUNS_SUBDIR
    if not runs_dir.exists():
        return
    cutoff = (now or time.time()) - ttl_days * 86400
    for entry in runs_dir.iterdir():
        if entry.suffix == ".json" and entry.stat().st_mtime < cutoff:
            entry.unlink(missing_ok=True)
