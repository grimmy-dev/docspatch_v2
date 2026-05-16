"""Source-analysis types."""

from dataclasses import dataclass, field


@dataclass
class FunctionMetadata:
    name: str
    signature: str
    docstring: str | None = None
    line_start: int = 0
    line_end: int = 0


@dataclass
class FileSummary:
    path: str
    summary: str
    functions: list[FunctionMetadata] = field(default_factory=list)
    content_hash: str = ""


@dataclass
class SemanticChange:
    path: str
    old_hash: str
    new_hash: str
    changed_functions: list[str] = field(default_factory=list)
