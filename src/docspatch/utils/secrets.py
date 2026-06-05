"""Scrubs and masks sensitive API keys in plaintext to prevent exposure."""

import re

_API_KEY_RE = re.compile(r"\b(sk-[A-Za-z0-9_-]{6,}|AIza[A-Za-z0-9_-]{10,})\b")
"""Provider key shapes: Anthropic/OpenAI ``sk-…``, Google ``AIza…``."""

_MASK = "••••••••"
_MIN_REGISTERED_LEN = 8
"""Shorter strings are too generic to mask by exact match without false hits."""

_active_keys: set[str] = set()
"""API keys loaded this process. ``scrub`` masks them by exact match, catching
keys whose shape ``_API_KEY_RE`` would miss."""


def register_secret(value: object) -> None:
    """Save a key to the list of active secrets for exact-match scrubbing.

    Args:
        value: Secret string to register.
    """
    if value and isinstance(value, str) and len(value) >= _MIN_REGISTERED_LEN:
        _active_keys.add(value)


def is_secret_key(key: str) -> bool:
    """Identify configuration keys that contain sensitive values based on their name.

    Args:
        key: Configuration key name.

    Returns:
        True if the key name identifies a secret.
    """
    return key.startswith("api_key")


def mask_api_key(value: object) -> str:
    """Mask an API key, retaining only its first four characters.

    Args:
        value: Plaintext key string to mask.

    Returns:
        Masked key string, or a dash if empty.
    """
    if not value:
        return "—"
    s = str(value)
    return (s[:4] + "••••••••") if len(s) > 4 else "••••••••"


def scrub(text: str) -> str:
    """Scan text to replace occurrences of API keys with their masked equivalents.

    Args:
        text: Source text to scrub.

    Returns:
        Text with all identified API keys replaced.
    """
    masked = _API_KEY_RE.sub(lambda m: m.group(0)[:4] + _MASK, text)
    for key in _active_keys:
        if key in masked:
            masked = masked.replace(key, key[:4] + _MASK)
    return masked


def display_value(key: str, value: object) -> str:
    """Render a configuration value, masking it if the key corresponds to a secret.

    Args:
        key: Configuration key name.
        value: Value to format.

    Returns:
        Formatted configuration value.
    """
    if is_secret_key(key):
        return mask_api_key(value)
    return str(value) if value is not None else "—"
