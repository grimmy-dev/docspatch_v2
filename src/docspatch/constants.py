"""Project-wide domain constants. Single source of truth for config defaults and key-sets."""

from typing import Final

TONES: Final[dict[str, str]] = {
    "technical": "Precise; assumes domain knowledge.",
    "professional": "Clear and polished; suitable for all audiences.",
    "casual": "Friendly and approachable.",
}

# --- Config schema ---

GLOBAL_CONFIG_KEYS: Final[frozenset[str]] = frozenset({"provider"})
REPO_CONFIG_KEYS: Final[frozenset[str]] = frozenset(
    {"generator_model", "scout_model", "tone", "batch_token_limit", "concurrency_limit", "call_timeout"}
)
INT_CONFIG_KEYS: Final[frozenset[str]] = frozenset(
    {"batch_token_limit", "concurrency_limit", "call_timeout"}
)

DEFAULT_TONE: Final[str] = "professional"
DEFAULT_BATCH_TOKEN_LIMIT: Final[int] = 10000
DEFAULT_CONCURRENCY_LIMIT: Final[int] = 2
DEFAULT_CALL_TIMEOUT: Final[int] = 120

CONFIG_DEFAULTS: Final[dict[str, str | int | None]] = {
    "provider": None,
    "api_key": None,
    "generator_model": None,
    "scout_model": None,
    "tone": DEFAULT_TONE,
    "batch_token_limit": DEFAULT_BATCH_TOKEN_LIMIT,
    "concurrency_limit": DEFAULT_CONCURRENCY_LIMIT,
    "call_timeout": DEFAULT_CALL_TIMEOUT,
}
