"""Secret-handling helpers. Single source of truth for masking sensitive values."""

import re

_API_KEY_RE = re.compile(r"\b(sk-[A-Za-z0-9_-]{6,}|AIza[A-Za-z0-9_-]{10,})\b")
"""Provider key shapes: Anthropic/OpenAI ``sk-…``, Google ``AIza…``."""


def is_secret_key(key: str) -> bool:
    """Return True for config keys whose value must never appear unmasked."""
    return key.startswith("api_key")


def mask_api_key(value: object) -> str:
    """Mask all but the first 4 characters of an API key. Returns '—' for falsy input."""
    if not value:
        return "—"
    s = str(value)
    return (s[:4] + "••••••••") if len(s) > 4 else "••••••••"


def scrub(text: str) -> str:
    """Mask any API-key-shaped token found in free text (error messages, logs)."""
    return _API_KEY_RE.sub(lambda m: m.group(0)[:4] + "••••••••", text)


def display_value(key: str, value: object) -> str:
    """Render a config value for display, masking when `key` is secret."""
    if is_secret_key(key):
        return mask_api_key(value)
    return str(value) if value is not None else "—"
