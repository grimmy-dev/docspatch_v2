"""Defines the application exception hierarchy and terminal error renderers."""

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
    """Truncate diagnostic strings that exceed maximum console display lengths.

    Args:
        value: String text to potentially shorten.

    Returns:
        The shortened text with a truncation notice, or the original string.
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
        """Initialize the base application exception with diagnostic context and resolution advice.

        Args:
            message: Explanation of why the exception occurred.
            hint: Actionable advice on how to resolve the problem.
            context: Extra key-value diagnostics captured at the failure site.
        """
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.context = context or {}

    def render(self, debug: bool = False) -> Group:
        """Build a formatted terminal error view highlighting the code, message, and diagnostic context.

        Args:
            debug: Flag to output internal key-value diagnostics.

        Returns:
            A styled Rich Group containing error lines.
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
        """Instantiate an error indicating that a subprocess git execution failed.

        Args:
            cmd: List of command arguments passed to Git.
            stderr: Error output captured from git's standard error stream.

        Returns:
            A GitError instance with command and output diagnostics.
        """
        return cls(f"git command failed: {' '.join(cmd)}", hint=stderr.strip())


class ConfigError(DocspatchError):
    """Config missing, invalid, or unreadable."""

    code: ClassVar[str] = "docspatch.config"

    @classmethod
    def unknown_tier(cls, value: str) -> ConfigError:
        """Instantiate an error representing an invalid LLM model tier selection.

        Args:
            value: The unsupported tier string that was provided.

        Returns:
            A ConfigError detailing the invalid tier.
        """
        return cls(f"Unknown tier: {value!r}", hint="Choose: fast, balanced, best")

    @classmethod
    def unknown_provider(cls, value: str) -> ConfigError:
        """Instantiate an error representing an invalid LLM provider selection.

        Args:
            value: The unsupported provider string that was provided.

        Returns:
            A ConfigError detailing the invalid provider.
        """
        return cls(f"Unknown provider: {value!r}", hint="Choose: anthropic, openai, gemini")

    @classmethod
    def unknown_key(cls, key: str, valid: list[str]) -> ConfigError:
        """Instantiate an error representing an unrecognized configuration settings name.

        Args:
            key: The invalid setting name.
            valid: Collection of allowed configuration keys.

        Returns:
            A ConfigError detailing the unknown key and listing suggestions.
        """
        return cls(f"Unknown config key: {key!r}", hint=f"Valid keys: {', '.join(valid)}")

    @classmethod
    def must_be_int(cls, key: str, value: str, exc: Exception) -> ConfigError:
        """Instantiate an error indicating a configuration value failed integer conversion.

        Args:
            key: The name of the option.
            value: The invalid value that could not be cast.
            exc: The underlying ValueError exception that occurred.

        Returns:
            A ConfigError capturing the conversion failure details.
        """
        return cls(f"{key} must be an integer (got {value!r})", hint=str(exc))

    @classmethod
    def must_be_non_negative(cls, field: str, value: float) -> ConfigError:
        """Instantiate an error indicating a positive numeric configuration was less than zero.

        Args:
            field: The name of the invalid setting.
            value: The negative numeric value provided.

        Returns:
            A ConfigError capturing the value validation failure.
        """
        return cls(f"{field} must be ≥ 0 (got {value})", hint=f"Pass a value ≥ 0 for {field}.")

    @classmethod
    def invalid_api_key(cls, provider: str) -> ConfigError:
        """Instantiate an error representing a rejected LLM credential.

        Args:
            provider: Name of the service provider rejecting the key.

        Returns:
            A ConfigError indicating key rejection.
        """
        return cls(f"Invalid {provider} API key.", hint="Check your key and try again.")

    @classmethod
    def missing_api_key(cls, provider: str) -> ConfigError:
        """Instantiate an error indicating a required LLM credential is not set.

        Args:
            provider: Name of the provider requiring an API key.

        Returns:
            A ConfigError indicating key absence.
        """
        return cls(f"No API key configured for {provider}.", hint=f"Run `dp config set api_key_{provider} <key>`.")

    @classmethod
    def key_validation_failed(cls, exc: Exception) -> ConfigError:
        """Instantiate an error wrapping a failed credential validation check.

        Args:
            exc: The underlying connection or credential validation error.

        Returns:
            A ConfigError enclosing the verification failure.
        """
        return cls(f"Key validation failed: {exc}", hint="Check your key.")

    @classmethod
    def conflicting_flags(cls, a: str, b: str, hint: str) -> ConfigError:
        """Instantiate an error when mutually exclusive runtime options are selected.

        Args:
            a: First conflicting CLI flag name.
            b: Second conflicting CLI flag name.
            hint: Actionable explanation of how to adjust the flags.

        Returns:
            A ConfigError detailing the flag conflict.
        """
        return cls(f"--{a} and --{b} cannot be used together.", hint=hint)

    @classmethod
    def no_runs_to_resume(cls) -> ConfigError:
        """Instantiate an error when a user attempts to resume a non-existent execution.

        Returns:
            A ConfigError indicating there is no run history to pick up.
        """
        return cls("No incomplete runs to resume.", hint="Start a fresh run with `dp docs`.")

    @classmethod
    def headless_no_input(cls, question: str) -> ConfigError:
        """Instantiate an error when an interactive decision is required in a headless execution environment.

        Args:
            question: The text of the prompt that was blocked.

        Returns:
            A ConfigError indicating interaction was blocked.
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
        """Instantiate an error wrapping an unhandled API error from an LLM provider.

        Args:
            exc: The underlying provider API exception.

        Returns:
            A transient LLMError wrapping the API exception.
        """
        return cls(str(exc), hint="Check your API key and model availability.")


class TransientExhausted(LLMError):
    """Retry budget for a transient (rate-limit / 5xx / timeout) call ran out.

    Distinct subclass so any pipeline (docs, readme, future ones) can offer
    the user a provider/model switch instead of aborting the whole run.
    """

    code: ClassVar[str] = "docspatch.llm.transient_exhausted"

    @classmethod
    def after(cls, attempts: int, exc: Exception) -> TransientExhausted:
        """Instantiate an error indicating retries for temporary API errors have been exhausted.

        Args:
            attempts: Number of retry attempts made before giving up.
            exc: The final failure exception encountered.

        Returns:
            A TransientExhausted error instance.
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
        """Initialize an error for model response parsing failures, capturing the raw input payload.

        Args:
            raw_output: Unstructured response string received from the model.
        """
        super().__init__(message, hint, context)
        self.raw_output = raw_output

    @classmethod
    def after_retry(cls, exc: Exception) -> ParseFailed:
        """Instantiate an error when model parsing schema checks fail even after retry attempts.

        Args:
            exc: The final validation schema exception.

        Returns:
            A ParseFailed error capturing the schema failure.
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
        """Instantiate an error representing a missing file system path.

        Args:
            path: Missing target path.

        Returns:
            A PathError denoting a missing target.
        """
        return cls(f"Path not found: {path}", hint="Pass a path that exists, ideally repo-relative.")

    @classmethod
    def not_python(cls, path: str) -> PathError:
        """Instantiate an error when a file is processed that is not Python code.

        Args:
            path: The path of the non-Python target.

        Returns:
            A PathError denoting a file type mismatch.
        """
        return cls(f"Not a Python file: {path}", hint="dp docs only operates on .py files.")

    @classmethod
    def outside_repo(cls, path: str, repo_root: str) -> PathError:
        """Instantiate an error when a relative path exits the active repository tree.

        Args:
            path: Target path residing outside the workspace.
            repo_root: Active root directory of the repository.

        Returns:
            A PathError indicating an out-of-bounds target.
        """
        return cls(f"Path is outside the repo: {path}", hint=f"Pass a path under {repo_root}.")

    @classmethod
    def absolute_path(cls, abs_path: str, rel_path: str) -> PathError:
        """Instantiate an error indicating an absolute path was passed instead of a relative path.

        Args:
            abs_path: Absolute path that triggered the error.
            rel_path: Normalized repository-relative version of the path.

        Returns:
            A PathError requesting a repository-relative path.
        """
        return cls(f"Use a repo-relative path, not absolute: {abs_path}", hint=f"Try: {rel_path}")

    @classmethod
    def ignored(cls, path: str) -> PathError:
        """Instantiate an error when a path matches exclusion patterns.

        Args:
            path: Target path that was excluded.

        Returns:
            A PathError denoting an ignored target.
        """
        return cls(f"Path matches .docsignore: {path}", hint="Use `--no-ignore` to override.")


class ReadmeError(DocspatchError):
    """README generation cannot proceed with the current inputs."""

    code: ClassVar[str] = "docspatch.readme"

    @classmethod
    def not_a_directory(cls, path: str) -> ReadmeError:
        """Instantiate an error when a file is passed to a directory-only readme command.

        Args:
            path: The file path that was provided.

        Returns:
            A ReadmeError denoting a directory is required.
        """
        return cls(f"readme operates on directories, not files: {path}", hint="Pass a directory or omit the path for the repo root.")


class LockError(DocspatchError):
    """Another docs run holds the per-repo lock."""

    code: ClassVar[str] = "docspatch.lock"

    @classmethod
    def run_in_progress(cls, pid: int, started: float) -> LockError:
        """Instantiate an error indicating that a concurrent process is running.

        Args:
            pid: Process ID holding the active lock.
            started: Epoch timestamp when the existing run began.

        Returns:
            A LockError indicating concurrent execution is blocked.
        """
        return cls(
            f"Another docs run is in progress (PID {pid}, started {time.ctime(started)}).",
            hint="Wait for it to finish, or delete .docspatch/run.lock if that process is gone.",
        )


class RunTimeout(DocspatchError):
    """A run's active work ran past its time budget — likely a stuck pipeline."""

    code: ClassVar[str] = "docspatch.timeout"
    exit_code: ClassVar[int] = EXIT_TRANSIENT

    @classmethod
    def exceeded(cls, budget: float) -> RunTimeout:
        """Instantiate an error for a run that overran its active-time budget.

        Args:
            budget: The active-work budget in seconds that was exceeded.

        Returns:
            A RunTimeout indicating the run was aborted.
        """
        minutes = int(budget // 60)
        return cls(
            f"Run aborted after {minutes} min of active work — the pipeline appears stuck.",
            hint="Re-run with --resume to continue, or narrow the scope.",
        )


class CacheError(DocspatchError):
    """Cache read/write failed — a corrupt or unreachable cache is a bug."""

    code: ClassVar[str] = "docspatch.cache"
    exit_code: ClassVar[int] = EXIT_INTERNAL

    @classmethod
    def read_failed(cls, path: str, exc: Exception) -> CacheError:
        """Instantiate an error representing a cache file read failure.

        Args:
            path: File system path of the unreadable cache.
            exc: The underlying reading exception.

        Returns:
            A CacheError indicating cache read failure.
        """
        return cls(f"Failed to read cache for {path}", hint=str(exc))

    @classmethod
    def write_failed(cls, path: str, exc: Exception) -> CacheError:
        """Instantiate an error representing a cache file write failure.

        Args:
            path: File system path of the cache destination.
            exc: The underlying write exception.

        Returns:
            A CacheError indicating cache write failure.
        """
        return cls(f"Failed to write cache for {path}", hint=str(exc))
