"""Generate and manage the unified markdown summary file for the project."""

from collections.abc import Iterable
from pathlib import Path

from docspatch.cache import ScoutCache
from docspatch.pipelines.scout.grouping import group_by_dir
from docspatch.schemas import FileSummary, FunctionMetadata, ProjectOverviewOutput
from docspatch.utils.fs import atomic_write
from docspatch.utils.project import (
    ProjectFacts,
    entry_point_targets,
    is_entry_point_path,
    project_facts,
)

MARKER_OPEN = '<!-- dp:file path="{path}" -->'
MARKER_OPEN_TIERED = '<!-- dp:file path="{path}" tier="{tier}" -->'
MARKER_CLOSE = "<!-- /dp:file -->"
PROJECT_OPEN = "<!-- dp:project -->"
PROJECT_CLOSE = "<!-- /dp:project -->"
UNIFIED_NAME = "CONTEXT.md"
INTERNAL_TIER = "internal"


def resolve_internal_paths(
    summaries: Iterable[FileSummary],
    overview: ProjectOverviewOutput | None,
    entry_modules: set[str],
) -> set[str]:
    """Return the paths the README view should drop as internal.

    The S1 deterministic floor wins: an entry-point target is never internal,
    whatever the model said. The LLM tag from the overview decides the rest. With
    no overview the floor is all we have, so nothing is dropped (S1 alone).

    Args:
        summaries: The per-file summaries being written.
        overview: The synthesized overview carrying the LLM file tiers, or None.
        entry_modules: Dotted entry-point modules forming the public floor.

    Returns:
        The set of repo-relative paths tagged internal.
    """
    if overview is None:
        return set()
    tiers = overview.file_tiers
    return {
        s.path
        for s in summaries
        if tiers.get(s.path) == INTERNAL_TIER and not is_entry_point_path(s.path, entry_modules)
    }


def render_project_block(facts: ProjectFacts, overview: ProjectOverviewOutput | None) -> str:
    """Render the project-level preamble that heads CONTEXT.md.

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


def render_block(summary: FileSummary, *, internal: bool = False, detailed: bool = False) -> str:
    """Produce a markdown-formatted block for a single file summary.

    Args:
        summary: The file summary data.
        internal: Whether to tag the block's marker as internal tier.
        detailed: Whether to render each function with its full signature and
            docstring. Used for entry-point modules, whose signatures and
            argument help are the project's documented public contract.

    Returns:
        The rendered markdown block.
    """
    open_marker = (
        MARKER_OPEN_TIERED.format(path=summary.path, tier=INTERNAL_TIER)
        if internal
        else MARKER_OPEN.format(path=summary.path)
    )
    lines = [
        open_marker,
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
        lines += _detailed_function(fn) if detailed else [_brief_function(fn)]
    lines.append(MARKER_CLOSE)
    return "\n".join(lines)


def _brief_function(fn: FunctionMetadata) -> str:
    """Render a function as a single summary line.

    Returns:
        The ``- name — summary`` line.
    """
    note = fn.llm_summary or fn.docstring
    suffix = f" — {note.splitlines()[0]}" if note else ""
    return f"- {fn.name}{suffix}"


def _detailed_function(fn: FunctionMetadata) -> list[str]:
    """Render a function as its signature plus indented docstring.

    Surfaces the real parameters and their help — for a command this is the
    arguments and options a README must document — straight from the source,
    so nothing is invented.

    Returns:
        The signature line followed by the indented docstring lines.
    """
    out = [f"- `{fn.signature}`"]
    body = fn.docstring or fn.llm_summary
    if body:
        out += [f"  {line}" for line in body.splitlines()]
    return out


def render_unified(
    summaries: Iterable[FileSummary],
    facts: ProjectFacts,
    overview: ProjectOverviewOutput | None,
    entry_modules: set[str] | None = None,
) -> str:
    """Assemble the project preamble and per-file blocks into the unified document.

    Args:
        summaries: The collection of summaries to process.
        facts: Deterministic project metadata for the preamble.
        overview: The synthesized project overview, or None for facts only.
        entry_modules: Dotted entry-point modules forming the public floor; the
            README tier is omitted when none are given.

    Returns:
        The complete unified markdown document.
    """
    summaries = list(summaries)
    modules = entry_modules or set()
    internal = resolve_internal_paths(summaries, overview, modules)
    blocks: list[str] = [render_project_block(facts, overview)]
    for directory, grouped in group_by_dir(summaries):
        blocks.append(f"# {directory}")
        for summary in grouped:
            is_internal = summary.path in internal
            # Public modules carry their real signatures and docstrings — the
            # documented surface a README is written from. Internal modules,
            # dropped from the README view anyway, stay one line to save tokens.
            blocks.append(render_block(summary, internal=is_internal, detailed=not is_internal))
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
    rendered = render_unified(summaries, project_facts(repo_root), overview, entry_point_targets(repo_root))
    atomic_write(out_path, rendered)
    return out_path
