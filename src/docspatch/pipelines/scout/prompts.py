"""Prompt templates for the scout pipeline. Single source of truth for wording."""

from collections.abc import Sequence

from docspatch.pipelines.scout.types import FileMiss

PATH_HEADER = "===== PATH: {path} ====="


def build_batch_prompt(misses: Sequence[FileMiss]) -> str:
    """Build one batched summarisation prompt for ``misses``.

    Each file is delimited by a ``PATH_HEADER`` line so the LLM cannot confuse
    boundaries even when source content includes ``---`` style separators.
    """
    paths = "\n".join(f"- {m.path}" for m in misses)
    blocks = "\n\n".join(f"{PATH_HEADER.format(path=m.path)}\n{m.compressed}" for m in misses)
    return (
        "Summarize each Python module below.\n"
        "For each file: 3-4 sentences covering purpose, key abstractions, "
        "data flow, and any notable behaviour or side effects.\n"
        "For each function: 2 sentences — what it does and what it returns or raises.\n"
        "Start all summaries with a verb. No filler, no LLM-ese.\n\n"
        f"Expected paths:\n{paths}\n\n"
        f"{blocks}"
    )
