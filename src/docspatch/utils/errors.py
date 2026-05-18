"""Docspatch error hierarchy. Single source of truth for raise + render."""

from __future__ import annotations

from typing import ClassVar

from rich.console import Group
from rich.text import Text


class DocspatchError(Exception):
    """Base error.

    Attributes:
        message: User-facing failure description.
        hint: Optional actionable next step.
        context: Optional structured detail (key=value lines under the hint).
    """

    code: ClassVar[str] = "docspatch.error"

    def __init__(
        self,
        message: str,
        hint: str = "",
        context: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.context = context or {}

    def render(self) -> Group:
        """Return a rich renderable: ``Error: …`` + optional ``Hint:`` + context."""
        lines: list[Text] = [Text.assemble(("Error: ", "bold red"), (self.message, "red"))]
        if self.hint:
            lines.append(Text.assemble(("Hint:  ", "yellow"), self.hint))
        for k, v in self.context.items():
            lines.append(Text.assemble((f"  {k}: ", "dim"), v))
        return Group(*lines)


class GitError(DocspatchError):
    """Git operation failed or not in a git repo."""

    code: ClassVar[str] = "docspatch.git"

    @classmethod
    def command_failed(cls, cmd: list[str], stderr: str) -> GitError:
        return cls(f"git command failed: {' '.join(cmd)}", hint=stderr.strip())


class ConfigError(DocspatchError):
    """Config missing, invalid, or unreadable."""

    code: ClassVar[str] = "docspatch.config"

    @classmethod
    def unknown_tier(cls, value: str) -> ConfigError:
        return cls(f"Unknown tier: {value!r}", hint="Choose: fast, balanced, best")

    @classmethod
    def unknown_provider(cls, value: str) -> ConfigError:
        return cls(f"Unknown provider: {value!r}", hint="Choose: anthropic, openai, gemini")

    @classmethod
    def unknown_key(cls, key: str, valid: list[str]) -> ConfigError:
        return cls(f"Unknown config key: {key!r}", hint=f"Valid keys: {', '.join(valid)}")

    @classmethod
    def must_be_int(cls, key: str, value: str, exc: Exception) -> ConfigError:
        return cls(f"{key} must be an integer (got {value!r})", hint=str(exc))

    @classmethod
    def must_be_non_negative(cls, field: str, value: float) -> ConfigError:
        return cls(f"{field} must be ≥ 0 (got {value})")

    @classmethod
    def invalid_api_key(cls, provider: str) -> ConfigError:
        return cls(f"Invalid {provider} API key.", hint="Check your key and try again.")

    @classmethod
    def key_validation_failed(cls, exc: Exception) -> ConfigError:
        return cls(f"Key validation failed: {exc}", hint="Check your key.")


class LLMError(DocspatchError):
    """LLM API call failed."""

    code: ClassVar[str] = "docspatch.llm"

    @classmethod
    def api_failure(cls, exc: Exception) -> LLMError:
        return cls(str(exc), hint="Check your API key and model availability.")


class TransientExhausted(LLMError):
    """Retry budget for a transient (rate-limit / 5xx / timeout) call ran out.

    Distinct subclass so any pipeline (scout, generator, future ones) can offer
    the user a provider/model switch instead of aborting the whole run.
    """

    code: ClassVar[str] = "docspatch.llm.transient_exhausted"

    @classmethod
    def after(cls, attempts: int, exc: Exception) -> TransientExhausted:
        return cls(str(exc), hint=f"Rate limit: retried {attempts} times.")


class CacheError(DocspatchError):
    """Cache read/write failed."""

    code: ClassVar[str] = "docspatch.cache"

    @classmethod
    def read_failed(cls, path: str, exc: Exception) -> CacheError:
        return cls(f"Failed to read cache for {path}", hint=str(exc))

    @classmethod
    def write_failed(cls, path: str, exc: Exception) -> CacheError:
        return cls(f"Failed to write cache for {path}", hint=str(exc))
