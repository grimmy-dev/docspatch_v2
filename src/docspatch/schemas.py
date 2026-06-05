"""Contains validated settings schemas and type mappings for configuring LLM clients."""

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
    """Validate and cast a string to a recognized LLM provider literal.

    Args:
        value: The raw provider identifier string.

    Returns:
        The cast provider literal.

    Raises:
        ConfigError: The provider name is unrecognized.
    """
    if value not in get_args(Provider):
        raise ConfigError.unknown_provider(value)
    return cast(Provider, value)


def as_tier(value: str) -> Tier:
    """Validate and cast a string to a recognized model performance tier.

    Args:
        value: The raw tier string.

    Returns:
        The cast tier literal.

    Raises:
        ConfigError: The tier name is unrecognized.
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
    """Resolve the default configuration value from global settings.

    Args:
        key: The configuration key to query.

    Returns:
        A scoped value containing the default value.
    """
    return ScopedValue(CONFIG_DEFAULTS[key], "default")


@dataclass
class DocspatchConfig:
    provider: ScopedValue[str | None] = field(default_factory=lambda: _default("provider"))
    api_key: ScopedValue[str | None] = field(default_factory=lambda: _default("api_key"))
    generator_model: ScopedValue[str | None] = field(default_factory=lambda: _default("generator_model"))
    analysis_model: ScopedValue[str | None] = field(default_factory=lambda: _default("analysis_model"))
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
        """Construct run settings from a config object, applying environment-specific fallbacks.

        Args:
            config: The loaded application configuration.

        Returns:
            A structured settings object initialized with resolved run options.
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


# ---- LLM structured-output schemas -----------------------------------------


class ReadmeOutput(BaseModel):
    """A whole README rendered as a single markdown document."""

    markdown: str = Field(description="The complete README in GitHub-flavoured markdown. No code fences around the whole document.")


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
