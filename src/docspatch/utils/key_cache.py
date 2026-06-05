"""Caches validated API keys in a local JSON file to avoid redundant verification calls."""

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
    """Return the standard local filesystem path for the API key validation JSON file.

    Returns:
        Path to the validation cache file.
    """
    return Path.home() / ".docspatch" / ".key_validation.json"


def _hash(api_key: str) -> str:
    """Compute the SHA-256 hex digest of an API key string.

    Args:
        api_key: Plaintext API key to hash.

    Returns:
        Hexadecimal representation of the hashed key.
    """
    return hashlib.sha256(api_key.encode()).hexdigest()


def _load(path: Path) -> dict[str, _Entry]:
    """Load and parse cached validation records from a JSON file.

    Args:
        path: Path to the validation JSON file.

    Returns:
        Dictionary of cache entries mapped by provider.
    """
    try:
        raw = json.loads(path.read_text())
    except OSError, json.JSONDecodeError:
        return {}
    return raw if isinstance(raw, dict) else {}


def _save(path: Path, data: dict[str, _Entry]) -> None:
    """Save API key validation records to a persistent JSON file.

    Args:
        path: Location to write the JSON file.
        data: Dictionary of cache records to save.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def is_validated(provider: str, api_key: str, *, path: Path | None = None, now: float | None = None) -> bool:
    """Check if a cached API key hash exists and is within its time-to-live threshold.

    Args:
        provider: Name of the service provider.
        api_key: Plaintext API key to check.
        path: Custom cache file path, or null to use the default path.
        now: Override timestamp for testing, or null to use current epoch time.

    Returns:
        True if the cached key matches and has not expired.
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
    """Write a validated API key hash and timestamp record to the cache file.

    Args:
        provider: Name of the service provider.
        api_key: Plaintext API key that was validated.
        path: Custom cache file path, or null to use the default path.
        now: Override timestamp for testing, or null to use current epoch time.
    """
    p = path or default_path()
    data = _load(p)
    current = now if now is not None else time.time()
    data[provider] = {"hash": _hash(api_key), "validated_at": current}
    _save(p, data)
