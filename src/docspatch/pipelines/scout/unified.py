"""Generate and manage the unified markdown summary file for the project."""

from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

from docspatch.cache import ScoutCache
from docspatch.schemas import FileSummary, ProjectOverviewOutput
from docspatch.utils.fs import atomic_write
from docspatch.utils.project import ProjectFacts, project_facts

MARKER_OPEN = '<!-- dp:file path="{path}" -->'
MARKER_CLOSE = "<!-- /dp:file -->"
PROJECT_OPEN = "<!-- dp:project -->"
PROJECT_CLOSE = "<!-- /dp:project -->"
UNIFIED_NAME = "SUMMARY.md"


def render_project_block(facts: ProjectFacts, overview: ProjectOverviewOutput | None) -> str:
    """Render the project-level preamble that heads SUMMARY.md.

    Args:
        facts: Deterministic metadata from pyproject.
        overview: The synthesized overview, or None to render facts only.

    Returns:
        The rendered markdown block, wrapped in dp:project markers.
    """
    lines = [PROJECT_OPEN, f"# {facts.name}"]
    if facts.description:
        lines.append(facts.description)
    if facts.labelled:
        lines.append("")
        lines.append(" | ".join(f"**{label}:** {value}" for label, value in facts.labelled))
    if overview is not None:
        lines += ["", "## Architecture", overview.summary, "", overview.architecture]
        if overview.components:
            lines.append("")
            lines.append("### Components")
            lines += [f"- **{c.name}** — {c.role}" for c in overview.components]
    lines.append(PROJECT_CLOSE)
    return "\n".join(lines)


def render_block(summary: FileSummary) -> str:
    """Produce a markdown-formatted block for a single file summary.

    Args:
        summary: The file summary data.

    Returns:
        The rendered markdown block.
    """
    lines = [
        MARKER_OPEN.format(path=summary.path),
        f"## {Path(summary.path).name}",
        summary.summary,
    ]
    if summary.interfaces:
        lines.append("**Interfaces:** " + ", ".join(summary.interfaces))
    if summary.relationships:
        lines.append("**Relationships:** " + ", ".join(summary.relationships))
    if summary.change_note:
        lines.append(f"**Changed:** {summary.change_note}")
    for fn in summary.functions:
        note = fn.llm_summary or fn.docstring
        suffix = f" — {note.splitlines()[0]}" if note else ""
        lines.append(f"- {fn.name}{suffix}")
    lines.append(MARKER_CLOSE)
    return "\n".join(lines)


def render_unified(
    summaries: Iterable[FileSummary],
    facts: ProjectFacts,
    overview: ProjectOverviewOutput | None,
) -> str:
    """Assemble the project preamble and per-file blocks into the unified document.

    Args:
        summaries: The collection of summaries to process.
        facts: Deterministic project metadata for the preamble.
        overview: The synthesized project overview, or None for facts only.

    Returns:
        The complete unified markdown document.
    """
    by_dir: dict[str, list[FileSummary]] = defaultdict(list)
    for summary in summaries:
        by_dir[str(Path(summary.path).parent)].append(summary)

    blocks: list[str] = [render_project_block(facts, overview)]
    for directory in sorted(by_dir):
        blocks.append(f"# {directory}")
        for summary in sorted(by_dir[directory], key=lambda s: s.path):
            blocks.append(render_block(summary))
    return "\n".join(blocks) + "\n"


def write_unified(
    cache: ScoutCache,
    paths: Iterable[str],
    repo_root: Path,
    overview: ProjectOverviewOutput | None,
) -> Path:
    """Write the updated unified summary file to the repository.

    Args:
        cache: The cache storage.
        paths: The set of paths to include in the summary.
        repo_root: The filesystem root of the repository.
        overview: The synthesized project overview, or None for facts only.

    Returns:
        The path to the created summary file.
    """
    summaries = [s for p in paths if (s := cache.get(p)) is not None]
    out_path = repo_root / ".docspatch" / UNIFIED_NAME
    atomic_write(out_path, render_unified(summaries, project_facts(repo_root), overview))
    return out_path
