"""Prompt assembly for the three README LLM passes: triage, drill, and generation."""

from docspatch.pipelines.readme.state import PreContext, Surface

# ---- shared fragments ------------------------------------------------------

TOOL_DEFS = (
    "Tools available to this pipeline (you do not call them yourself — you name what you need "
    "and the pipeline fetches it):\n"
    "- get_file_surface(path): public functions and classes of a file, with signatures and "
    "docstrings but no bodies.\n"
    "- get_function_body(path, function_name): the full implementation of one function, "
    "compressed. Reserve this for entry points and orchestrators whose behaviour you must "
    "describe precisely — never request every function.\n"
)

_GROUND_RULES = (
    "Write the README the way a maintainer who genuinely cares about this project writes one: "
    "someone who knows it cold, believes it solves a real problem well, and wants a working "
    "developer to understand it, want it, and run it in a couple of minutes. Use "
    "GitHub-flavoured markdown.\n"
    "\n"
    "Voice:\n"
    "- Plain, direct, concrete. Active voice, present tense. No padding.\n"
    "- Address the reader as 'you' when describing usage.\n"
    "- Open by naming the problem this project solves and what makes its approach worth choosing — "
    "be specific and let real capability carry the interest. Earned conviction, never empty "
    "superlatives.\n"
    "- No hype, no AI throat-clearing — drop 'powerful', 'seamlessly', 'robust', 'comprehensive', "
    "'In today's world…', and the like. Show why it's good by being concrete about what it does, "
    "not by asserting that it is good.\n"
    "- Show usage with a runnable command, and explain around it — never leave a command bare.\n"
    "\n"
    "Depth: be genuinely descriptive — a thin README reads like the author didn't care. Give the "
    "things a user reaches for — main commands, public API, key configuration, the headline "
    "features — a real explanation: what it does, when you'd reach for it, how it fits the "
    "workflow, and behaviour worth knowing, typically three to five sentences. Draw the connections "
    "between pieces so a newcomer sees the whole, not a flat list. Match depth to importance; a "
    "minor flag stays one line, but never shortchange what carries the project.\n"
    "\n"
    "Grounding: every concrete specific — command, flag, argument, function name, signature, "
    "import path, dependency — must come verbatim from the context shown. Never invent one. Prose "
    "explanation of behaviour is free; invented specifics are forbidden. Output the markdown "
    "document only — no surrounding code fences, no preamble.\n"
)


def scope_label(scope: str) -> str:
    """Describe the README's target in prose for a prompt header.

    Args:
        scope: Target scope directory.

    Returns:
        A phrase naming the whole project or a specific package.
    """
    return "the whole project" if scope in {".", "", "./"} else f"the `{scope}` package"


def render_facts(pre: PreContext) -> str:
    """Render authoritative project facts and dependencies, or empty for a subpackage.

    Args:
        pre: The run backbone.

    Returns:
        A labelled facts block, or an empty string when no facts apply.
    """
    if pre.facts is None:
        return ""
    lines = [f"Project name: {pre.facts.name}"]
    if pre.facts.description:
        lines.append(f"Description: {pre.facts.description}")
    lines += [f"{label}: {value}" for label, value in pre.facts.labelled]
    if pre.dependencies:
        lines.append("Dependencies: " + ", ".join(pre.dependencies))
    return "Project facts (authoritative):\n" + "\n".join(lines) + "\n\n"


def render_backbone(pre: PreContext) -> str:
    """Render the facts and change-tagged directory tree shared by every pass.

    Args:
        pre: The run backbone.

    Returns:
        The facts plus tagged directory layout.
    """
    return f"{render_facts(pre)}Directory layout (tags mark files changed since the last README):\n{pre.tagged_tree}\n\n"


def render_surface(surface: Surface) -> str:
    """Render one file's public surface as a prompt block.

    Args:
        surface: The file surface from Tool 2.

    Returns:
        The path header, module docstring, and each public entry.
    """
    lines = [f"### {surface.path}"]
    if surface.module_doc:
        lines.append(surface.module_doc.strip())
    for entry in surface.entries:
        lines.append(f"- {entry.signature}")
        if entry.docstring:
            doc = "\n".join(f"    {line}" for line in entry.docstring.strip().splitlines())
            lines.append(doc)
    return "\n".join(lines)


def render_surfaces(surfaces: list[Surface]) -> str:
    """Join several file surfaces into one prompt section.

    Args:
        surfaces: The surfaces to render, in the order they should appear.

    Returns:
        The concatenated surface blocks.
    """
    return "\n\n".join(render_surface(s) for s in surfaces)


# ---- pass prompts ----------------------------------------------------------


def build_triage_prompt(pre: PreContext) -> str:
    """Build the triage prompt: pick the files worth surfacing for this scope.

    Args:
        pre: The run backbone (tagged tree, facts, tool menu).

    Returns:
        The complete triage prompt.
    """
    return (
        f"You are scoping a README for {scope_label(pre.scope)}. Select every source file whose "
        "public surface a thorough README should draw on — entry points and CLI commands, the "
        "public API, the modules that define what the project does and how its main features work, "
        "and the orchestrators that tie them together. Err toward inclusion: a slightly wider set "
        "yields a richer, more accurate README, and surfacing is cheap. Skip only clear noise — "
        "tests, private plumbing, and files a README would never reference. Tagged files changed "
        "recently and are likely relevant. Return only repo-relative paths drawn from the tree.\n\n"
        f"{render_backbone(pre)}"
        f"{pre.tool_defs}"
    )


def build_drill_prompt(pre: PreContext, rendered_surfaces: str, error: str | None = None) -> str:
    """Build the drill prompt: request needed bodies and synthesize an orientation.

    Args:
        pre: The run backbone.
        rendered_surfaces: The selected files' surfaces, already rendered.
        error: A prior bad-plan error to correct, or null on the first attempt.

    Returns:
        The complete drill prompt.
    """
    retry = (
        f"\nYour previous plan was rejected: {error}\nRequest only paths and function names that "
        "appear in the surfaces below.\n"
        if error
        else ""
    )
    return (
        f"You are writing a README for {scope_label(pre.scope)}. Below are the public surfaces of "
        "the selected files. Two outputs:\n"
        "1. A required synthesis (4-6 sentences) that orients the README author: the problem the "
        "project solves and who it's for, what its main entry points and commands do, how the major "
        "pieces fit together and the data or control flow between them, and any design choice or "
        "behaviour that makes the project distinctive. Write it as confident, concrete prose — this "
        "is the spine the README is built on. Always produce it, even if you request no bodies.\n"
        "2. The implementation bodies you need to describe behaviour precisely and accurately. Be "
        "generous: request the entry points, the command handlers, the orchestrators, and any "
        "public function whose real behaviour, options, or output shape the README should state "
        "exactly rather than guess. Reading the real code is cheap and prevents vague or wrong "
        "claims. Don't request trivial getters or obvious one-liners, but don't starve the README "
        "either. Leave the list empty only when the surfaces genuinely already tell the whole "
        "story.\n"
        f"{retry}\n"
        f"{render_backbone(pre)}"
        f"Selected file surfaces:\n{rendered_surfaces}\n"
    )


def build_generator_prompt(scope: str, woven: str, existing_readme: str | None, feedback: str | None) -> str:
    """Build the generator prompt from the woven context and the existing README.

    The existing README is framed as baseline, tone, and user preference: match
    its voice and structure, keep hand-written sections, refresh facts from the
    woven context. A fresh run has none and picks a default voice.

    Args:
        scope: The repo-relative scope.
        woven: The assembled context (backbone, synthesis, surfaces, bodies).
        existing_readme: The current README, or null for a first write.
        feedback: Accumulated revise feedback, or null.

    Returns:
        The complete generator prompt.
    """
    existing = (
        "Existing README — this is the baseline, the tone reference, and the user's preference. "
        "Match its voice and structure, preserve every hand-written section (license, configuration, "
        "contributing, badges, links), and refresh only the facts that the context below updates:\n"
        f"{existing_readme}\n\n"
        if existing_readme
        else ""
    )
    tail = f"\nRevise per this feedback (apply all):\n{feedback}\n" if feedback else ""
    return (
        f"{_GROUND_RULES}\n"
        f"Write a README for {scope_label(scope)}.\n\n"
        "The context below opens with a shared understanding of the project — internalise it as the "
        "project's intent and write in alignment with it, then ground every concrete specific in the "
        "facts, surfaces, and implementations that follow.\n\n"
        f"{existing}"
        f"Project context (authoritative — ground every specific in this):\n{woven}\n"
        f"{tail}"
    )
