"""LLM output schema types."""

from dataclasses import dataclass, field
from typing import Protocol, TypeVar

T_co = TypeVar("T_co", covariant=True)


class StructuredChain(Protocol[T_co]):
    """Typed async chain returned by LLMClient.with_structured_output()."""

    async def ainvoke(self, input: str) -> T_co: ...


@dataclass
class FileSummaryOutput:
    summary: str
    key_symbols: list[str] = field(default_factory=list)


@dataclass
class DocstringOutput:
    docstring: str


@dataclass
class ChangelogEntry:
    version: str
    entries: list[str] = field(default_factory=list)
