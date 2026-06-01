"""Manage a persistent cache for API key validation status."""

import hashlib
import json
import time
from pathlib import Path
from typing import Final, TypedDict

CACHE_TTL_SECONDS: Final[int] = 600


class _Entry(TypedDict):
    hash: str
    validated_at: float


def default_path() -> Path:
    """Return the standard path for storing API key validations."""
    return Path.home() / ".docspatch" / ".key_validation.json"


def _hash(api_key: str) -> str:
    """Generate a SHA256 hash for an API key.

    Args:
        api_key: Sensitive key to hash.

    Returns:
        The hexadecimal hash string.
    """
    return hashlib.sha256(api_key.encode()).hexdigest()


def _load(path: Path) -> dict[str, _Entry]:
    """Retrieve cached validation entries from the disk.

    Args:
        path: Location of the cache file.

    Returns:
        The dictionary of validated providers and metadata.
    """
    try:
        raw = json.loads(path.read_text())
    except OSError, json.JSONDecodeError:
        return {}
    return raw if isinstance(raw, dict) else {}


def _save(path: Path, data: dict[str, _Entry]) -> None:
    """Write validation entries to the persistent disk cache.

    Args:
        path: Location to save the cache.
        data: Validation records to persist.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def is_validated(provider: str, api_key: str, *, path: Path | None = None, now: float | None = None) -> bool:
    """Check if an API key has been validated within the configured time-to-live.

    Args:
        provider: Service provider name.
        api_key: The key to verify.
        path: Cache file location.
        now: Current time for TTL comparison.

    Returns:
        True if the key is still valid.
    """
    entry = _load(path or default_path()).get(provider)
    if entry is None:
        return False
    if entry.get("hash") != _hash(api_key):
        return False
    ts = entry.get("validated_at", 0.0)
    current = now if now is not None else time.time()
    return current - ts < CACHE_TTL_SECONDS


def mark_validated(provider: str, api_key: str, *, path: Path | None = None, now: float | None = None) -> None:
    """Register that a provider's API key has successfully passed validation.

    Args:
        provider: Name of the service provider.
        api_key: The API key string.
        path: Location of the cache file.
        now: Current timestamp.
    """
    p = path or default_path()
    data = _load(p)
    current = now if now is not None else time.time()
    data[provider] = {"hash": _hash(api_key), "validated_at": current}
    _save(p, data)
