"""Checkpoint storage: sqlite saver paths, run-id, janitor."""

import secrets
from datetime import UTC, datetime


def make_run_id() -> str:
    """Return ``YYYYMMDD-HHMMSS-<6 hex>`` (UTC). Human-sortable + collision-safe."""
    return f"{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"
