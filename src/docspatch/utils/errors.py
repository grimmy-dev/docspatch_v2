"""Define custom exception types and error rendering logic for docspatch."""

from __future__ import annotations

import time
from typing import ClassVar, Final

from rich.console import Group
from rich.text import Text

from docspatch.utils.secrets import is_secret_key, mask_api_key, scrub

# Process exit codes (PRD R12). 0 success is owned by the CLI, not raised here.
EXIT_USER_ERROR: Final[int] = 1  # bad config / auth / scope — the user can fix it
EXIT_TRANSIENT: Final[int] = 2  # provider down / rate-limited — retry may succeed
EXIT_INTERNAL: Final[int] = 3  # internal bug — should not happen

_CONTEXT_VALUE_LIMIT: Final[int] = 120


def _truncate(value: str) -> str:
    """Shorten a string if it exceeds the length limit for error contexts.

    Args:
        value: String to potentially shorten.

    Returns:
        The truncated string with a suffix or the original string.
    """
    if len(value) <= _CONTEXT_VALUE_LIMIT:
        return value
    return value[:_CONTEXT_VALUE_LIMIT] + "... (truncated)"


class DocspatchError(Exception):
    """Base error.

    Attributes:
        message: User-facing failure description.
        hint: Optional actionable next step.
        context: Optional structured detail (key=value lines, shown with --debug).
    """

    code: ClassVar[str] = "docspatch.error"
    exit_code: ClassVar[int] = EXIT_USER_ERROR

    def __init__(
        self,
        message: str,
        hint: str = "",
        context: dict[str, str] | None = None,
    ) -> None:
        """Initialize a base docspatch exception.

        Args:
            message: The error description.
            hint: A suggestion for fixing the issue.
            context: A mapping of relevant diagnostic metadata.
        """
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.context = context or {}

    def render(self, debug: bool = False) -> Group:
        """Generate a visual display of the error for terminal output.

        Args:
            debug: Toggle inclusion of raw error context.

        Returns:
            A rich renderable group.
        """
        lines: list[Text] = [Text.assemble((f"[{self.code}] ", "dim red"), (scrub(self.message), "bold red"))]
        if self.hint:
            lines.append(Text.assemble(("Hint:  ", "yellow"), scrub(self.hint)))
        if debug:
            for k, v in self.context.items():
                shown = mask_api_key(v) if is_secret_key(k) else scrub(_truncate(v))
                lines.append(Text.assemble((f"  {k}: ", "dim"), shown))
        return Group(*lines)


class GitError(DocspatchError):
    """Git operation failed or not in a git repo."""

    code: ClassVar[str] = "docspatch.git"

    @classmethod
    def command_failed(cls, cmd: list[str], stderr: str) -> GitError:
        """Create an error for a failed shell git command.

        Args:
            cmd: The command executed.
            stderr: The error output.
        """
        return cls(f"git command failed: {' '.join(cmd)}", hint=stderr.strip())


class ConfigError(DocspatchError):
    """Config missing, invalid, or unreadable."""

    code: ClassVar[str] = "docspatch.config"

    @classmethod
    def unknown_tier(cls, value: str) -> ConfigError:
        """Create an error for an unsupported model tier.

        Args:
            value: The invalid tier string.
        """
        return cls(f"Unknown tier: {value!r}", hint="Choose: fast, balanced, best")

    @classmethod
    def unknown_provider(cls, value: str) -> ConfigError:
        """Create an error for an unsupported LLM provider.

        Args:
            value: The invalid provider string.
        """
        return cls(f"Unknown provider: {value!r}", hint="Choose: anthropic, openai, gemini")

    @classmethod
    def unknown_key(cls, key: str, valid: list[str]) -> ConfigError:
        """Create an error for a configuration key that does not exist.

        Args:
            key: The invalid key string.
            valid: A list of allowed configuration keys.
        """
        return cls(f"Unknown config key: {key!r}", hint=f"Valid keys: {', '.join(valid)}")

    @classmethod
    def must_be_int(cls, key: str, value: str, exc: Exception) -> ConfigError:
        """Create an error for a configuration value requiring an integer.

        Args:
            key: The setting key.
            value: The invalid raw value.
            exc: The original conversion exception.
        """
        return cls(f"{key} must be an integer (got {value!r})", hint=str(exc))

    @classmethod
    def must_be_non_negative(cls, field: str, value: float) -> ConfigError:
        """Create an error for a numeric configuration value that must be positive.

        Args:
            field: The field name.
            value: The invalid value.
        """
        return cls(f"{field} must be ≥ 0 (got {value})", hint=f"Pass a value ≥ 0 for {field}.")

    @classmethod
    def invalid_api_key(cls, provider: str) -> ConfigError:
        """Create an error for an API key that failed authentication.

        Args:
            provider: The LLM service provider.
        """
        return cls(f"Invalid {provider} API key.", hint="Check your key and try again.")

    @classmethod
    def missing_api_key(cls, provider: str) -> ConfigError:
        """Create an error for an absent API key.

        Args:
            provider: The LLM service provider.
        """
        return cls(f"No API key configured for {provider}.", hint=f"Run `dp config set api_key_{provider} <key>`.")

    @classmethod
    def key_validation_failed(cls, exc: Exception) -> ConfigError:
        """Create an error for a failed API key validation check.

        Args:
            exc: The reason for the validation failure.
        """
        return cls(f"Key validation failed: {exc}", hint="Check your key.")

    @classmethod
    def conflicting_flags(cls, a: str, b: str, hint: str) -> ConfigError:
        """Create an error for two run flags that cannot be combined.

        Args:
            a: The first conflicting flag.
            b: The second conflicting flag.
            hint: The explanation.
        """
        return cls(f"--{a} and --{b} cannot be used together.", hint=hint)

    @classmethod
    def no_runs_to_resume(cls) -> ConfigError:
        """Create an error when no incomplete run exists to resume."""
        return cls("No incomplete runs to resume.", hint="Start a fresh run with `dp docs`.")

    @classmethod
    def headless_no_input(cls, question: str) -> ConfigError:
        """Create an error when input is requested in a headless mode.

        Args:
            question: The prompt that was blocked.
        """
        return cls(
            f"Cannot prompt in a non-interactive session: {question!r}",
            hint="Run in a terminal, or set the required config value beforehand.",
        )


class LLMError(DocspatchError):
    """LLM API call failed — usually a provider-side fault, so retryable."""

    code: ClassVar[str] = "docspatch.llm"
    exit_code: ClassVar[int] = EXIT_TRANSIENT

    @classmethod
    def api_failure(cls, exc: Exception) -> LLMError:
        """Create an error for failures during LLM API interactions.

        Args:
            exc: The underlying API error.
        """
        return cls(str(exc), hint="Check your API key and model availability.")


class TransientExhausted(LLMError):
    """Retry budget for a transient (rate-limit / 5xx / timeout) call ran out.

    Distinct subclass so any pipeline (scout, generator, future ones) can offer
    the user a provider/model switch instead of aborting the whole run.
    """

    code: ClassVar[str] = "docspatch.llm.transient_exhausted"

    @classmethod
    def after(cls, attempts: int, exc: Exception) -> TransientExhausted:
        """Create an error when transient retries have been exhausted.

        Args:
            attempts: Number of retries performed.
            exc: The final error.
        """
        return cls(str(exc), hint=f"Rate limit: retried {attempts} times.")


class ParseFailed(LLMError):
    """Structured output failed schema validation twice (initial call + one retry).

    Distinct from :class:`TransientExhausted`: a parse failure is never retried
    further — the offending item is flagged for review instead.
    """

    code: ClassVar[str] = "docspatch.llm.parse_failed"
    # Not retryable — the item is flagged for review, so this is a user-side call.
    exit_code: ClassVar[int] = EXIT_USER_ERROR

    def __init__(
        self,
        message: str,
        hint: str = "",
        context: dict[str, str] | None = None,
        raw_output: str = "",
    ) -> None:
        """Initialize a parse failure error with raw output captured.

        Args:
            raw_output: The unparseable data received from the LLM.
        """
        super().__init__(message, hint, context)
        self.raw_output = raw_output

    @classmethod
    def after_retry(cls, exc: Exception) -> ParseFailed:
        """Create an error when parsing continues to fail after retries.

        Args:
            exc: The final schema validation error.
        """
        return cls(
            "Model response failed schema validation after one retry.",
            hint="The item is flagged for review — rerun or reject it.",
            raw_output=str(exc),
        )


class PathError(DocspatchError):
    """File or directory path is invalid for the requested operation."""

    code: ClassVar[str] = "docspatch.path"

    @classmethod
    def not_found(cls, path: str) -> PathError:
        """Create an error for a file path that is missing.

        Args:
            path: The missing path.
        """
        return cls(f"Path not found: {path}", hint="Pass a path that exists, ideally repo-relative.")

    @classmethod
    def not_python(cls, path: str) -> PathError:
        """Create an error for a non-Python file input.

        Args:
            path: The invalid path.
        """
        return cls(f"Not a Python file: {path}", hint="dp docs only operates on .py files.")

    @classmethod
    def outside_repo(cls, path: str, repo_root: str) -> PathError:
        """Create an error for paths that reside outside the repository.

        Args:
            path: The invalid path.
            repo_root: The base repository directory.
        """
        return cls(f"Path is outside the repo: {path}", hint=f"Pass a path under {repo_root}.")

    @classmethod
    def absolute_path(cls, abs_path: str, rel_path: str) -> PathError:
        """Create an error for when an absolute path is provided.

        Args:
            abs_path: The absolute path provided.
            rel_path: The recommended relative path.
        """
        return cls(f"Use a repo-relative path, not absolute: {abs_path}", hint=f"Try: {rel_path}")

    @classmethod
    def ignored(cls, path: str) -> PathError:
        """Create an error for paths matched by ignore rules.

        Args:
            path: The ignored path.
        """
        return cls(f"Path matches .docsignore: {path}", hint="Use `--no-ignore` to override.")


class LockError(DocspatchError):
    """Another docs run holds the per-repo lock."""

    code: ClassVar[str] = "docspatch.lock"

    @classmethod
    def run_in_progress(cls, pid: int, started: float) -> LockError:
        """Create an error when a concurrent run is detected.

        Args:
            pid: The ID of the process holding the lock.
            started: The timestamp when the current run started.
        """
        return cls(
            f"Another docs run is in progress (PID {pid}, started {time.ctime(started)}).",
            hint="Wait for it to finish, or delete .docspatch/run.lock if that process is gone.",
        )


class CacheError(DocspatchError):
    """Cache read/write failed — a corrupt or unreachable cache is a bug."""

    code: ClassVar[str] = "docspatch.cache"
    exit_code: ClassVar[int] = EXIT_INTERNAL

    @classmethod
    def read_failed(cls, path: str, exc: Exception) -> CacheError:
        """Create an error for failures reading the cache.

        Args:
            path: The cache file path.
            exc: The cause of the error.
        """
        return cls(f"Failed to read cache for {path}", hint=str(exc))

    @classmethod
    def write_failed(cls, path: str, exc: Exception) -> CacheError:
        """Create an error for failures writing to the cache.

        Args:
            path: The cache file path.
            exc: The cause of the error.
        """
        return cls(f"Failed to write cache for {path}", hint=str(exc))
