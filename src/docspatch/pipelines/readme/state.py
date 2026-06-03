"""Data models representing the final README generation results."""

from dataclasses import dataclass
from pathlib import Path

from docspatch.llm import TokenUsage


@dataclass(frozen=True)
class ReadmeResult:
    """Outcome of a README run.

    ``out_path`` is the written file when ``written`` is true, else null (the
    user cancelled). ``usage`` totals every generation call, revisions included.
    """

    written: bool
    out_path: Path | None
    usage: TokenUsage
