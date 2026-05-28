"""Cross-process API key validation cache.

A key is validated by the provider via :meth:`LLMClient.validate_key`. That
call costs a network round-trip; doing it on every ``dp`` invocation is
wasteful. This cache stores ``sha256(api_key) + validated_at`` per provider
so subsequent invocations within the TTL skip the round-trip.

Auto-invalidation:
- TTL: 10 minutes since the last successful validation.
- Hash mismatch: if the user changes ``api_key_<provider>`` (via
  ``dp config set`` or by editing the file), the new key's hash will not
  match the cached one — :func:`is_validated` returns False without us
  needing to wipe the entry explicitly.
"""

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
    """Return the default path for storing API key validations."""
    return Path.home() / ".docspatch" / ".key_validation.json"


def _hash(api_key: str) -> str:
    """Generate a SHA256 hash for an API key."""
    return hashlib.sha256(api_key.encode()).hexdigest()


def _load(path: Path) -> dict[str, _Entry]:
    """Load cached validation entries from a file."""
    try:
        raw = json.loads(path.read_text())
    except OSError, json.JSONDecodeError:
        return {}
    return raw if isinstance(raw, dict) else {}


def _save(path: Path, data: dict[str, _Entry]) -> None:
    """Save validation entries to a persistent cache file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def is_validated(provider: str, api_key: str, *, path: Path | None = None, now: float | None = None) -> bool:
    """True iff ``api_key`` for ``provider`` was validated within the TTL."""
    entry = _load(path or default_path()).get(provider)
    if entry is None:
        return False
    if entry.get("hash") != _hash(api_key):
        return False
    ts = entry.get("validated_at", 0.0)
    current = now if now is not None else time.time()
    return current - ts < CACHE_TTL_SECONDS


def mark_validated(provider: str, api_key: str, *, path: Path | None = None, now: float | None = None) -> None:
    """Record that ``api_key`` for ``provider`` just passed validation."""
    p = path or default_path()
    data = _load(p)
    current = now if now is not None else time.time()
    data[provider] = {"hash": _hash(api_key), "validated_at": current}
    _save(p, data)
