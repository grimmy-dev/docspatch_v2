"""Prompt assembly templates for single-call and refine-fold README generation."""

from dataclasses import dataclass, field

from docspatch.pipelines.readme.markers import FileBlock
from docspatch.utils.project import ProjectFacts

_GROUND_RULES = (
    "Write the README the way a senior maintainer writes one for a project they know cold: the "
    "reader is a working developer who wants to understand and run it in two minutes. Use "
    "GitHub-flavoured markdown.\n"
    "\n"
    "Voice:\n"
    "- Plain, direct, and concrete. Active voice, present tense. Clear sentences, no padding.\n"
    "- Address the reader as 'you' when describing usage.\n"
    "- Lead with substance: say what it does and why you'd reach for it, not how impressive it is.\n"
    "- No hype and no AI throat-clearing — drop 'This project is designed to…', 'In today's "
    "world…', 'seamlessly', 'powerful', 'robust', 'comprehensive', 'effortless', and the like.\n"
    "- Show usage with a runnable command, and explain around it — don't leave a command bare.\n"
    "\n"
    "Be descriptive where it matters, never padded:\n"
    "- A README is documentation, not a reference card. Give the things a user actually reaches "
    "for — the main commands, the public API, key configuration, major features — a real "
    "explanation: what it does, when you'd use it, and any behaviour worth knowing, usually two to "
    "four sentences. Spend the words where they help.\n"
    "- Match depth to importance. Do not inflate a trivial or rarely-used entry into a paragraph; a "
    "minor flag can stay one line. Depth is for what carries weight, not everything.\n"
    "- You may synthesise that explanation from the module summary, its relationships, and the "
    "project overview; you are not limited to echoing a one-line note. Connect a piece to the "
    "workflow it sits in.\n"
    "- Never make things up. This freedom is for explaining real behaviour only — it never "
    "licenses inventing concrete specifics (see the grounding rule). When the summaries do not "
    "support a claim, leave it out. Describe richly; fabricate nothing.\n"
    "\n"
    "Rules:\n"
    "- Grounding: every concrete specific — command, flag, argument, function name, signature, "
    "import path, return shape, dependency — must come verbatim from the facts, interfaces, or "
    "signatures shown. Never invent or guess one. If you have a name but not its signature, show "
    "the import or describe it in prose rather than fabricate a call. (Prose explanation of "
    "behaviour is free; only invented specifics are forbidden.)\n"
    "- Output the markdown document only — no surrounding code fences, no preamble.\n"
    "- Open with one concrete sentence naming the project and what it does for whom.\n"
    "- Be specific to this codebase: real modules, commands, and entry points from the facts and "
    "summaries — never boilerplate that would fit any project.\n"
    "- Cover, at minimum: a title, a one-line description, install steps, usage grounded in the "
    "project's declared entry points or public API, and at least one runnable example.\n"
    "- When a project overview is provided, ground the intro in it and add a short 'How it works' "
    "(or architecture) section a few sentences long: explain the main pieces and how data or "
    "control flows between them, synthesised from the overview and the modules' relationships — "
    "not a list restating each module. This is the section that turns a command list into "
    "documentation a newcomer can reason about.\n"
    "- The summaries below are already limited to the project's public surface. Do not add a "
    "section heading for any module that is not among them.\n"
    "- When a module gives a function's full signature and docstring, that is the authoritative "
    "surface: document its arguments and options with the help text shown, and document a new "
    "entry as deeply as the existing entries around it — never a bare one-liner beside detailed "
    "siblings.\n"
    "\n"
    "Example opening (bad -> good); the good form names a real surface and skips the hype:\n"
    "  bad:  A powerful, comprehensive tool that seamlessly handles all your needs.\n"
    "  good: <name> turns OpenAPI specs into typed Python clients — one command, no runtime "
    "dependencies. Run `<cli> generate api.yaml`.\n"
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
    # Declared entry-point commands the README must document (root scope only);
    # empty for a library, which makes the coverage check a no-op.
    entry_points: tuple[str, ...] = ()
    # Module names tagged internal, which must never appear as a section heading.
    internal_modules: tuple[str, ...] = ()
    existing_readme: str | None = None
    # Rewrite freely for quality (restructure, reword) versus a minimal in-place
    # refresh that copies unchanged prose verbatim. Both stay anchored to the
    # existing README so real sections are never lost.
    rewrite: bool = False
    # Scout's synthesized architecture/components narrative, root scope only — a
    # subpackage README stays at its own altitude and skips repo-wide framing.
    project_overview: str | None = None
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


def _overview_block(ctx: ReadmeContext) -> str:
    """Render scout's project synthesis so the intro builds on it, not from scratch.

    Args:
        ctx: Current run context.

    Returns:
        The labelled overview section, or an empty string for a subpackage.
    """
    if not ctx.project_overview:
        return ""
    return (
        "Project overview (authoritative synthesis — ground the intro and any architecture "
        "section in this; do not contradict it):\n"
        f"{ctx.project_overview}\n\n"
    )


def _backbone_block(ctx: ReadmeContext) -> str:
    """Render the project identity every prompt path must carry.

    Bundles the authoritative facts (including declared entry points), the
    project overview, and the directory layout into one section. It is never
    sharded and never optional, so no generation path can draft without the
    project's identity in front of it.

    Args:
        ctx: Current run context.

    Returns:
        The combined facts + overview + directory-tree section.
    """
    return f"{_facts_block(ctx)}{_overview_block(ctx)}Directory layout:\n{ctx.dir_tree}\n\n"


def _existing_block(ctx: ReadmeContext) -> str:
    """Render the current README so the model builds on it instead of replacing it.

    Both modes stay anchored to the existing file: a refresh edits in place, a
    rewrite restructures freely — but neither may discard a section that exists
    only in the README (license, configuration, development, contributing), since
    the code summaries can never reconstruct those.

    Args:
        ctx: Current run context.

    Returns:
        The existing-README section, or an empty string when none exists.
    """
    if not ctx.existing_readme:
        return ""
    if ctx.rewrite:
        instruction = (
            "Existing README — rewrite it: you may restructure sections, reorder, and reword freely "
            "for clarity and a consistent voice. But this file is the source of truth for everything "
            "the code summaries do not contain — keep every section that carries real content, "
            "especially install commands, configuration, license, and development/contributing notes, "
            "and preserve its badges, links, and the package manager and install commands it uses. Do "
            "not drop a section just because no summary backs it, and do not invent a replacement for "
            "one. Fold in any commands, options, or surface the facts and summaries add:"
        )
    else:
        instruction = (
            "Existing README — revise it in place, do not rewrite it. Keep its structure, section "
            "order, headings, badges, and links. Treat every unchanged paragraph as a fixed string: "
            "copy it through byte-for-byte, keeping its exact line breaks, wrapping, punctuation, and "
            "quoting. Only the specific spans you are updating may differ. Change only what is out of "
            "date, missing, or gone:\n"
            "  - Add any part of the project's public surface the facts and summaries document but "
            "the README omits — whatever form it takes for this project.\n"
            "  - Correct anything now wrong.\n"
            "  - Remove documentation for a specific command, module, or feature that no longer "
            "appears in the facts or summaries — it has been deleted. Leave general sections (install, "
            "license, contributing, and the like) intact even though no summary backs them."
        )
    return f"{instruction}\n{ctx.existing_readme}\n\n"


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
        f"{_backbone_block(ctx)}"
        f"{_existing_block(ctx)}"
        f"Module summaries:\n{_summaries_text(blocks)}\n"
        f"{_instructions_tail(ctx)}"
    )


def build_refine_prompt(ctx: ReadmeContext, draft: str, blocks: list[FileBlock]) -> str:
    """Build a refine-step prompt that folds the next batch into a running draft.

    Used only when the slice overflows one call. The full backbone rides every
    step, so each fold revises with the project's identity in front of it — there
    is no blind partition draft.

    Args:
        ctx: Resolved facts, tree, and instructions for the run.
        draft: The running README from the prior fold steps.
        blocks: The next batch of file-summary blocks to integrate.

    Returns:
        The complete prompt string for this fold step.
    """
    return (
        f"{_GROUND_RULES}\n"
        f"Revise the README draft below for {_scope_label(ctx.scope)} so it also covers "
        "the additional modules. Keep what is already correct, integrate the new modules "
        "where they belong, and do not drop existing sections.\n\n"
        f"{_backbone_block(ctx)}"
        f"{_existing_block(ctx)}"
        f"Current draft:\n{draft}\n\n"
        f"Additional module summaries:\n{_summaries_text(blocks)}\n"
        f"{_instructions_tail(ctx)}"
    )
