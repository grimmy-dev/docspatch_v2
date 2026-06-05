"""Run checkpoint identifiers and management utility routines."""

import secrets
from datetime import UTC, datetime


def make_run_id() -> str:
    """Generate a unique, human-sortable run identifier.

    Returns:
        A string formatted as YYYYMMDD-HHMMSS-HEX.
    """
    return f"{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"
