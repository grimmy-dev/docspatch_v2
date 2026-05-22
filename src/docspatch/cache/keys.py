"""Cache key derivation. SHA-256 prefix keyed on repo-relative path."""

import hashlib

KEY_HEX_WIDTH = 32


def cache_key(rel_path: str, suffix: str = ".json.gz") -> str:
    """Deterministic filename for ``rel_path``. Stable across repo moves."""
    digest = hashlib.sha256(rel_path.encode()).hexdigest()[:KEY_HEX_WIDTH]
    return f"{digest}{suffix}"
