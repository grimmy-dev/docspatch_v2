"""Synthesize and persist the project-level overview that heads CONTEXT.md.

The overview is one LLM pass over the per-file summaries scout already produced
— it is never rebuilt from source. It is cached so unchanged runs pay nothing.
"""

import gzip
from collections.abc import Iterable
from pathlib import Path

from docspatch.llm import LLMClient, TokenUsage
from docspatch.pipelines.scout.grouping import group_by_dir
from docspatch.pipelines.scout.prompts import SUMMARY_VOICE
from docspatch.schemas import FileSummary, ProjectOverviewOutput
from docspatch.utils.fs import atomic_write

OVERVIEW_NAME = "overview.json.gz"


def overview_path(repo_root: Path) -> Path:
    """Return the on-disk location of the cached project overview.

    Returns:
        Path to the overview cache file.
    """
    return repo_root / ".docspatch" / "cache" / OVERVIEW_NAME


def read_overview(repo_root: Path) -> ProjectOverviewOutput | None:
    """Load the cached project overview, or None if absent or unreadable.

    Returns:
        The cached overview, or None when there is nothing usable to reuse.
    """
    path = overview_path(repo_root)
    if not path.exists():
        return None
    try:
        return ProjectOverviewOutput.model_validate_json(gzip.decompress(path.read_bytes()))
    except (ValueError, OSError):
        return None


def write_overview(repo_root: Path, overview: ProjectOverviewOutput) -> None:
    """Persist the project overview as gzipped JSON.

    Args:
        overview: The synthesized overview to cache.
    """
    atomic_write(overview_path(repo_root), gzip.compress(overview.model_dump_json().encode()))


def _overview_input(summaries: Iterable[FileSummary]) -> str:
    """Render per-file summaries into a directory-grouped prompt body.

    Only the file summary, interfaces, and relationships are included — the
    function-level detail is noise for project-level reasoning.

    Returns:
        The grouped summary text fed to the synthesis call.
    """
    lines: list[str] = []
    for directory, grouped in group_by_dir(summaries):
        lines.append(f"## {directory}")
        for summary in grouped:
            lines.append(f"- {summary.path}: {summary.summary}")
            if summary.interfaces:
                lines.append(f"  interfaces: {', '.join(summary.interfaces)}")
            if summary.relationships:
                lines.append(f"  relationships: {', '.join(summary.relationships)}")
    return "\n".join(lines)


def _build_prompt(summaries: Iterable[FileSummary]) -> str:
    """Construct the project-overview synthesis prompt.

    Returns:
        The complete prompt string.
    """
    return (
        "Below are per-file summaries of a codebase, grouped by directory. "
        "Synthesize a project-level overview for a reader who has never seen the code. "
        "Generalise from the summaries; do not just concatenate them.\n"
        "- summary: one paragraph on what the project does and who uses it.\n"
        "- architecture: how the codebase is organised and how the pieces interact, "
        "including the main data/control flow from entry point to output.\n"
        "- components: the major subsystems (package/pipeline level, not per file), "
        "each with a one-line role that names what it concretely does.\n"
        f"{SUMMARY_VOICE}"
        "Examples (bad -> good) component roles — each bad form opens with a vague verb "
        "or a marketing word; rewrite to a concrete one:\n"
        "  bad:  Handles various LLM-related operations.\n"
        "  good: Wraps Anthropic, OpenAI, and Gemini behind one retry-aware client.\n"
        "  bad:  Orchestrates complex LangGraph workflows for documentation.\n"
        "  good: Runs the docstring and scout pipelines as checkpointed LangGraph graphs.\n"
        "  bad:  Manages persistent, versioned storage of runs.\n"
        "  good: Stores run results as gzipped, schema-versioned JSON on disk.\n"
        "  bad:  Provides shared infrastructure and leverages LLMs.\n"
        "  good: Holds config, atomic file IO, git path filtering, and error types.\n"
        "Be concrete and specific to this codebase.\n\n"
        f"{_overview_input(summaries)}"
    )


async def synthesize_overview(
    client: LLMClient, summaries: Iterable[FileSummary]
) -> tuple[ProjectOverviewOutput, TokenUsage]:
    """Synthesize a project overview from existing per-file summaries.

    Args:
        client: LLM client used for the single synthesis call.
        summaries: The per-file summaries scout already produced.

    Returns:
        The structured project overview and the tokens its call consumed.

    Raises:
        TransientExhausted: The provider stayed unavailable through every retry.
        ParseFailed: The model never returned a valid overview.
    """
    chain = client.with_structured_output(ProjectOverviewOutput)
    return await chain.ainvoke(_build_prompt(summaries))
