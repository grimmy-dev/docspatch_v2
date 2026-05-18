"""Secret-handling helpers. Single source of truth for masking sensitive values."""


def is_secret_key(key: str) -> bool:
    """Return True for config keys whose value must never appear unmasked."""
    return key.startswith("api_key")


def mask_api_key(value: object) -> str:
    """Mask all but the first 4 characters of an API key. Returns '—' for falsy input."""
    if not value:
        return "—"
    s = str(value)
    return (s[:4] + "••••••••") if len(s) > 4 else "••••••••"


def display_value(key: str, value: object) -> str:
    """Render a config value for display, masking when `key` is secret."""
    if is_secret_key(key):
        return mask_api_key(value)
    return str(value) if value is not None else "—"
