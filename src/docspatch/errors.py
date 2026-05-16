"""Docspatch error hierarchy."""


class DocspatchError(Exception):
    """Base error. message shown to user; hint gives actionable guidance."""

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class GitError(DocspatchError):
    """Git operation failed or not in a git repo."""


class ConfigError(DocspatchError):
    """Config missing, invalid, or unreadable."""


class LLMError(DocspatchError):
    """LLM API call failed."""


class CacheError(DocspatchError):
    """Cache read/write failed."""
