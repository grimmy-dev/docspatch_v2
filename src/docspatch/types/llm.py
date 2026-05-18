"""LLM type surface: literals, narrowers, and structured-output schemas.

The narrowers (:func:`as_provider`, :func:`as_tier`) live here so the literal
types and the only safe way to obtain values of those types stay co-located —
callers import one module, not two.
"""

from typing import Literal, Protocol, TypeVar, cast, get_args

from pydantic import BaseModel, Field

from docspatch.utils.errors import ConfigError

T_co = TypeVar("T_co", covariant=True)

Provider = Literal["anthropic", "openai", "gemini"]
Tier = Literal["fast", "balanced", "best"]


def as_provider(value: str) -> Provider:
    """Narrow a raw string to the ``Provider`` literal. Raises on unknown."""
    if value not in get_args(Provider):
        raise ConfigError.unknown_provider(value)
    return cast(Provider, value)


def as_tier(value: str) -> Tier:
    """Narrow a raw string to the ``Tier`` literal. Raises on unknown."""
    if value not in get_args(Tier):
        raise ConfigError.unknown_tier(value)
    return cast(Tier, value)


class StructuredChain(Protocol[T_co]):
    """Typed async chain returned by ``LLMClient.with_structured_output()``."""

    async def ainvoke(self, prompt: str) -> T_co: ...


class FileSummaryOutput(BaseModel):
    """Module summary plus one-line description per function."""

    summary: str = Field(description="One decent paragraph overview of the module's purpose and functionality.")
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


class DocstringOutput(BaseModel):
    """Google-style docstring for a function."""

    docstring: str = Field(description="Google-style docstring body, no triple quotes.")


class ChangelogEntry(BaseModel):
    """Changelog entries for a single version."""

    version: str = Field(description="Semver version string, e.g. 1.2.0.")
    entries: list[str] = Field(default_factory=list, description="User-facing change lines.")
