"""Git-related types."""

from dataclasses import dataclass, field


@dataclass
class CommitInfo:
    sha: str
    message: str
    author: str
    timestamp: str
    files_changed: list[str] = field(default_factory=list)


@dataclass
class BreakingChange:
    function_name: str
    file_path: str
    description: str
