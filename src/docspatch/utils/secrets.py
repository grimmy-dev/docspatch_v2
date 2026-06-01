"""Manage and scrub API keys and sensitive configuration values."""

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
    """Register an active API key so scrub masks it even if the regex misses it.

    Args:
        value: The key string to register.
    """
    if value and isinstance(value, str) and len(value) >= _MIN_REGISTERED_LEN:
        _active_keys.add(value)


def is_secret_key(key: str) -> bool:
    """Return True for config keys whose value must never appear unmasked.

    Args:
        key: The configuration key name.

    Returns:
        Boolean indicating if the key is sensitive.
    """
    return key.startswith("api_key")


def mask_api_key(value: object) -> str:
    """Mask all but the first 4 characters of an API key; return '—' for empty input.

    Args:
        value: The key to mask.

    Returns:
        The masked key string.
    """
    if not value:
        return "—"
    s = str(value)
    return (s[:4] + "••••••••") if len(s) > 4 else "••••••••"


def scrub(text: str) -> str:
    """Mask API keys in free text using regex and exact registered key matches.

    Args:
        text: The input text containing potential keys.

    Returns:
        Text with sensitive values masked.
    """
    masked = _API_KEY_RE.sub(lambda m: m.group(0)[:4] + _MASK, text)
    for key in _active_keys:
        if key in masked:
            masked = masked.replace(key, key[:4] + _MASK)
    return masked


def display_value(key: str, value: object) -> str:
    """Render a config value for display, masking when key is secret.

    Args:
        key: The configuration key.
        value: The value to render.

    Returns:
        The displayed value string.
    """
    if is_secret_key(key):
        return mask_api_key(value)
    return str(value) if value is not None else "—"
