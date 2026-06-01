"""Define data schemas and configuration models for the application."""

from dataclasses import dataclass, field
from typing import Any, Literal, cast, get_args

from pydantic import BaseModel, Field

from docspatch.constants import (
    CONFIG_DEFAULTS,
    DEFAULT_BATCH_TOKEN_LIMIT,
    DEFAULT_CALL_TIMEOUT,
    DEFAULT_CONCURRENCY_LIMIT,
)
from docspatch.utils.errors import ConfigError

# ---- LLM literals + narrowers ----------------------------------------------

Provider = Literal["anthropic", "openai", "gemini"]
Tier = Literal["fast", "balanced", "best"]


def as_provider(value: str) -> Provider:
    """Convert a string to a recognized LLM provider literal.

    Args:
        value: The raw provider string.

    Returns:
        The validated provider literal.

    Raises:
        ConfigError: The value does not match any known provider.
    """
    if value not in get_args(Provider):
        raise ConfigError.unknown_provider(value)
    return cast(Provider, value)


def as_tier(value: str) -> Tier:
    """Convert a string to a recognized model tier literal.

    Args:
        value: The raw tier string.

    Returns:
        The validated tier literal.

    Raises:
        ConfigError: The value does not match any known tier.
    """
    if value not in get_args(Tier):
        raise ConfigError.unknown_tier(value)
    return cast(Tier, value)


# ---- Config types ----------------------------------------------------------

Scope = Literal["global", "repo", "default"]
ConfigValue = str | int | None
ConfigPatch = dict[str, ConfigValue]


@dataclass(frozen=True)
class ScopedValue[T]:
    value: T
    scope: Scope


def _default(key: str) -> ScopedValue[Any]:
    """Get the default value for a configuration key.

    Args:
        key: The configuration key to look up.

    Returns:
        A ScopedValue containing the default configuration.
    """
    return ScopedValue(CONFIG_DEFAULTS[key], "default")


@dataclass
class DocspatchConfig:
    provider: ScopedValue[str | None] = field(default_factory=lambda: _default("provider"))
    api_key: ScopedValue[str | None] = field(default_factory=lambda: _default("api_key"))
    generator_model: ScopedValue[str | None] = field(default_factory=lambda: _default("generator_model"))
    scout_model: ScopedValue[str | None] = field(default_factory=lambda: _default("scout_model"))
    tone: ScopedValue[str | None] = field(default_factory=lambda: _default("tone"))
    batch_token_limit: ScopedValue[int] = field(default_factory=lambda: _default("batch_token_limit"))
    concurrency_limit: ScopedValue[int] = field(default_factory=lambda: _default("concurrency_limit"))
    call_timeout: ScopedValue[int] = field(default_factory=lambda: _default("call_timeout"))


@dataclass(frozen=True)
class RunSettings:
    """Run parameters derived from config — the concrete int/float values a
    pipeline needs, resolved once from :class:`DocspatchConfig`.

    Keeping the ``config value or default`` derivation in one place stops it
    being re-done (and drifting) at every pipeline entry point.
    """

    batch_token_limit: int
    concurrency_limit: int
    call_timeout: float

    @classmethod
    def from_config(cls, config: DocspatchConfig) -> RunSettings:
        """Initialize settings from the application configuration.

        Args:
            config: The raw configuration object.

        Returns:
            An instance of RunSettings with defaults applied.
        """
        return cls(
            batch_token_limit=int(config.batch_token_limit.value or DEFAULT_BATCH_TOKEN_LIMIT),
            concurrency_limit=int(config.concurrency_limit.value or DEFAULT_CONCURRENCY_LIMIT),
            call_timeout=float(config.call_timeout.value or DEFAULT_CALL_TIMEOUT),
        )


# ---- Source-analysis types -------------------------------------------------


@dataclass
class FunctionMetadata:
    name: str
    signature: str
    docstring: str | None = None
    llm_summary: str | None = None
    line_start: int = 0
    line_end: int = 0


@dataclass
class FunctionDocState:
    """Hash + presence flag for a single function."""

    hash: str
    has_docstring: bool
    line_start: int = 0


@dataclass
class FileSummary:
    path: str
    summary: str
    functions: list[FunctionMetadata] = field(default_factory=list)
    interfaces: list[str] = field(default_factory=list)
    relationships: list[str] = field(default_factory=list)
    # Delta narrative vs the prior summary; None on the first summary.
    change_note: str | None = None
    # Compressed source kept so a later changed-file re-run can diff old vs new.
    compressed: str = ""
    content_hash: str = ""
    # size + mtime_ns power constant-time fast-skip before any read/parse.
    size: int = 0
    mtime_ns: int = 0


# ---- LLM structured-output schemas -----------------------------------------


class FileSummaryOutput(BaseModel):
    """Module summary, public surface, relationships, and per-function lines."""

    summary: str = Field(description="One decent paragraph overview of the module's purpose and functionality.")
    interfaces: list[str] = Field(
        default_factory=list,
        description="Public functions, classes, and exports a caller uses. One entry each.",
    )
    relationships: list[str] = Field(
        default_factory=list,
        description="Module connections: what it depends on and what depends on it.",
    )
    change_note: str | None = Field(
        default=None,
        description="One line on what changed since the prior version. Omit when summarising fresh.",
    )
    function_summaries: dict[str, str] = Field(
        default_factory=dict,
        description="Keyed by function name. Value = one concrete descriptive on what the function does.",
    )


class BatchSummaryOutput(BaseModel):
    """Summaries for a batch of modules, keyed by the path passed in the prompt."""

    files: dict[str, FileSummaryOutput] = Field(
        default_factory=dict,
        description="Mapping keyed by file path exactly as given in the `Expected paths` list.",
    )


class ArgDoc(BaseModel):
    """One parameter line under a docstring's ``Args:`` section."""

    name: str = Field(description="Parameter name exactly as it appears in the signature.")
    description: str = Field(description="What the parameter is, in one line.")


class RaiseDoc(BaseModel):
    """One exception line under a docstring's ``Raises:`` section."""

    exception: str = Field(description="Exception type the caller may see.")
    when: str = Field(description="Condition that triggers it.")


class DocstringSpec(BaseModel):
    """Structured docstring fields. The renderer turns these into Google-style text.

    Every section but ``description`` is optional: a void function leaves
    ``returns`` null, a function that raises nothing leaves ``raises`` empty.
    The renderer emits a section only when it is populated, so trivial functions
    get a one-line docstring and nothing more.
    """

    description: str = Field(description="One line stating what it does, imperative mood, ending with a period.")
    args: list[ArgDoc] = Field(
        default_factory=list,
        description="One entry per parameter worth explaining; omit self/cls and self-evident ones.",
    )
    returns: str | None = Field(default=None, description="What it returns. Null for functions that return None.")
    raises: list[RaiseDoc] = Field(default_factory=list, description="Exceptions a caller should anticipate; empty when none.")


class BatchDocstringOutput(BaseModel):
    """Docstring specs for a batch of targets, keyed by ``<rel>::<qualname>`` exactly as given in the prompt."""

    docstrings: dict[str, DocstringSpec] = Field(
        default_factory=dict,
        description="Mapping keyed by `<rel>::<qualname>` ids from the `Expected ids` list.",
    )
