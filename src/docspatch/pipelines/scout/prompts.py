"""Construct prompt templates for analyzing and summarizing code files within the scout pipeline."""

from collections.abc import Sequence

from docspatch.pipelines.scout.state import FileMiss

PATH_HEADER = "===== PATH: {path} ====="

# Shared voice for every summary the scout pipeline emits (per-file and project
# overview). The goal is documentation a new engineer (or an AI agent navigating
# the repo) can trust: precise, specific, and grounded in the actual code. A
# few-shot anchor plus a positive standard beat a bare "no LLM-ese" rule.
SUMMARY_VOICE = (
    "Voice: write like an experienced engineer documenting the system for a new "
    "teammate. Use precise, active, present-tense prose and the codebase's own "
    "terminology. Lead with a concrete verb and name the real mechanism, types, and "
    "data flow rather than the category of work. Favour specifics over generalities — "
    "say what it does and why it exists, including non-obvious decisions, constraints, "
    "and invariants. Do not open with vague verbs (Manage, Handle, Provide, Orchestrate, "
    "Coordinate, Implement, Enable, Support, Define), restate the name, hedge, or pad "
    "with marketing adjectives (robust, powerful, seamless, comprehensive).\n"
)


def render_file_block(miss: FileMiss) -> str:
    """Generate a formatted block containing file content and optional prior summary data.

    Args:
        miss: The file miss data containing source and potential prior state.

    Returns:
        The rendered string block.
    """
    head = f"{PATH_HEADER.format(path=miss.path)}\n{miss.compressed}"
    if miss.prior is None:
        return head
    return f"{head}\n--- Previous summary: {miss.prior.summary}\n--- Previous code:\n{miss.prior.compressed}"


def build_batch_prompt(misses: Sequence[FileMiss]) -> str:
    """Construct a prompt for summarizing a batch of files.

    Args:
        misses: The collection of files missing from cache.

    Returns:
        The complete prompt string.
    """
    paths = "\n".join(f"- {m.path}" for m in misses)
    blocks = "\n\n".join(render_file_block(m) for m in misses)
    change_line = (
        "- change_note: for any file showing a Previous summary and Previous code, "
        "one line on what changed since. Leave empty for files without prior context.\n"
        if any(m.prior for m in misses)
        else ""
    )
    return (
        "Summarize each Python module below for a maintainer building a mental model "
        "of the codebase. Read the actual code; do not guess from the file name.\n"
        "For each file:\n"
        "- summary: 3-4 sentences covering what the module is for, its key abstractions "
        "(the main types/functions and how they fit together), the data or control flow "
        "through it, and any non-obvious behaviour, invariant, or gotcha.\n"
        "- interfaces: the public functions/classes/exports a caller actually uses "
        "(names, not prose).\n"
        "- relationships: concrete dependencies — the notable modules/libraries it "
        "imports or calls, and what depends on it.\n"
        f"{change_line}"
        "For each function: 2 sentences — what it does and what it returns or raises.\n"
        f"{SUMMARY_VOICE}"
        "Example (bad -> good) summary opening:\n"
        "  bad:  Manage configuration for the application.\n"
        "  good: Merge global and per-repo TOML config, with repo values overriding global.\n\n"
        f"Expected paths:\n{paths}\n\n"
        f"{blocks}"
    )
