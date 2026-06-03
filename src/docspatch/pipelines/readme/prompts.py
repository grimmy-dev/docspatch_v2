"""Prompt assembly templates for README generation, map, and reduce stages."""

from dataclasses import dataclass, field

from docspatch.pipelines.readme.markers import FileBlock
from docspatch.utils.project import ProjectFacts

_GROUND_RULES = (
    "Write a README.md in GitHub-flavoured markdown. Rules:\n"
    "- Use only the information below. Do not invent commands, APIs, features, or dependencies.\n"
    "- Output the markdown document only — no surrounding code fences, no preamble.\n"
    "- Be concrete and specific to this codebase; skip filler and marketing language.\n"
)


@dataclass(frozen=True)
class ReadmeContext:
    """Everything a README prompt draws on, resolved once per run.

    ``facts`` and ``dependencies`` are populated for root scope only; a
    subpackage README omits project-level metadata.
    """

    scope: str
    dir_tree: str
    facts: ProjectFacts | None = None
    dependencies: tuple[str, ...] = ()
    existing_readme: str | None = None
    remarks: str | None = None
    feedback: tuple[str, ...] = field(default_factory=tuple)


def _scope_label(scope: str) -> str:
    """Describe the README's target in prose for the prompt header.

    Args:
        scope: Target scope directory.

    Returns:
        A human phrase naming the whole project or a specific package.
    """
    return "the whole project" if scope in {".", "", "./"} else f"the `{scope}` package"


def _facts_block(ctx: ReadmeContext) -> str:
    """Render the pyproject facts and dependencies, or empty for a subpackage.

    Args:
        ctx: Current run context.

    Returns:
        A labelled facts section, or an empty string when no facts apply.
    """
    if ctx.facts is None:
        return ""
    lines = [f"Project name: {ctx.facts.name}"]
    if ctx.facts.description:
        lines.append(f"Description: {ctx.facts.description}")
    lines += [f"{label}: {value}" for label, value in ctx.facts.labelled]
    if ctx.dependencies:
        lines.append("Dependencies: " + ", ".join(ctx.dependencies))
    return "Project facts (authoritative):\n" + "\n".join(lines) + "\n\n"


def _existing_block(ctx: ReadmeContext) -> str:
    """Render the current README so the model matches its tone and keeps links.

    Args:
        ctx: Current run context.

    Returns:
        The existing-README section, or an empty string when none exists.
    """
    if not ctx.existing_readme:
        return ""
    return (
        "Existing README (match its tone; preserve any badges and links, "
        "but refresh the content):\n"
        f"{ctx.existing_readme}\n\n"
    )


def _instructions_tail(ctx: ReadmeContext) -> str:
    """Append run-wide remarks and accumulated revise feedback, oldest first.

    Args:
        ctx: Current run context.

    Returns:
        The trailing instruction block, or an empty string when there is none.
    """
    parts: list[str] = []
    if ctx.remarks:
        parts.append(f"Additional instruction: {ctx.remarks}")
    if ctx.feedback:
        joined = "\n".join(f"- {note}" for note in ctx.feedback)
        parts.append(f"Revise per this feedback (apply all):\n{joined}")
    return ("\n" + "\n\n".join(parts) + "\n") if parts else ""


def _summaries_text(blocks: list[FileBlock]) -> str:
    """Join the selected file-summary blocks into one prompt section.

    Args:
        blocks: List of file-summary blocks.

    Returns:
        The concatenated module summaries.
    """
    return "\n\n".join(b.body for b in blocks)


def build_single_prompt(ctx: ReadmeContext, blocks: list[FileBlock]) -> str:
    """Build the one-shot prompt used when the scoped slice fits in one call.

    Args:
        ctx: Resolved facts, tree, and instructions for the run.
        blocks: The in-scope file-summary blocks.

    Returns:
        The complete prompt string.
    """
    return (
        f"{_GROUND_RULES}\n"
        f"Write a README for {_scope_label(ctx.scope)}.\n\n"
        f"{_facts_block(ctx)}"
        f"Directory layout:\n{ctx.dir_tree}\n\n"
        f"{_existing_block(ctx)}"
        f"Module summaries:\n{_summaries_text(blocks)}\n"
        f"{_instructions_tail(ctx)}"
    )


def build_map_prompt(ctx: ReadmeContext, blocks: list[FileBlock]) -> str:
    """Build a map-step prompt that drafts a README section for one partition.

    Args:
        ctx: Resolved facts, tree, and instructions for the run.
        blocks: The partition's file-summary blocks.

    Returns:
        The complete prompt string for the partition.
    """
    return (
        "Draft a focused README section for one part of a larger codebase. "
        "Cover only the modules below; another step will merge sections.\n"
        "Use only the information given; do not invent facts. Output markdown only.\n\n"
        f"Modules:\n{_summaries_text(blocks)}\n"
    )


def build_reduce_prompt(ctx: ReadmeContext, sections: list[str]) -> str:
    """Build the reduce-step prompt that merges drafted sections into one README.

    Args:
        ctx: Resolved facts, tree, and instructions for the run.
        sections: The per-partition draft sections from the map step.

    Returns:
        The complete prompt string for the merge.
    """
    drafts = "\n\n---\n\n".join(sections)
    return (
        f"{_GROUND_RULES}\n"
        f"Merge the draft sections below into one coherent README for "
        f"{_scope_label(ctx.scope)}. Remove redundancy, order the content "
        "logically, and add a single title and intro.\n\n"
        f"{_facts_block(ctx)}"
        f"Directory layout:\n{ctx.dir_tree}\n\n"
        f"{_existing_block(ctx)}"
        f"Draft sections:\n{drafts}\n"
        f"{_instructions_tail(ctx)}"
    )
