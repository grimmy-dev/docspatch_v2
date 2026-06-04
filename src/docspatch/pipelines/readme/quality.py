"""Deterministic quality checks that gate a README draft before review."""

import re
from dataclasses import dataclass

from docspatch.pipelines.readme.prompts import ReadmeContext

# Marketing tells that say nothing concrete about the project. Matched on word
# boundaries so legitimate words ("able", "support") are not hit as substrings.
MARKETING_WORDS: tuple[str, ...] = (
    "powerful",
    "seamless",
    "seamlessly",
    "robust",
    "comprehensive",
    "effortless",
    "effortlessly",
    "blazing",
    "blazingly",
    "cutting-edge",
    "state-of-the-art",
    "world-class",
    "best-in-class",
    "game-changing",
    "revolutionary",
    "supercharge",
    "unleash",
)

_MARKETING_RE = re.compile(r"\b(?:" + "|".join(re.escape(w) for w in MARKETING_WORDS) + r")\b")


@dataclass(frozen=True)
class Finding:
    """One quality problem in a draft. ``code`` is a stable tag; ``detail`` is the fix to feed back."""

    code: str
    detail: str


def inspect_readme(markdown: str, ctx: ReadmeContext) -> list[Finding]:
    """Report quality problems in a README draft, scope-aware for project facts.

    Args:
        markdown: The generated README markdown.
        ctx: The run context, used for the authoritative project facts.

    Returns:
        Every quality problem found; an empty list means the draft passes.
    """
    findings: list[Finding] = []
    stripped = markdown.strip()

    if stripped.startswith("```"):
        findings.append(Finding("fenced", "Remove the surrounding code fence; output the markdown document itself."))

    if not any(line.startswith("# ") for line in markdown.splitlines()):
        findings.append(Finding("no_title", "Add a single top-level title (a line starting with '# ')."))

    hits = sorted(set(_MARKETING_RE.findall(markdown.lower())))
    if hits:
        joined = ", ".join(hits)
        findings.append(Finding("marketing", f"Drop marketing language ({joined}); state concretely what the project does."))

    if ctx.facts is not None and ctx.facts.name and ctx.facts.name.lower() not in markdown.lower():
        findings.append(Finding("missing_name", f"Name the project ('{ctx.facts.name}') in the README."))

    findings += _entry_point_coverage(markdown, ctx)
    findings += _internal_leakage(markdown, ctx)
    return findings


def _entry_point_coverage(markdown: str, ctx: ReadmeContext) -> list[Finding]:
    """Flag any declared entry-point command the README never mentions.

    A no-op for a project that declares no scripts (a library or a service), so
    only repos that actually ship commands are held to this bar.

    Args:
        markdown: The generated README markdown.
        ctx: The run context carrying the declared entry-point commands.

    Returns:
        One finding per missing command, empty when all are covered.
    """
    lowered = markdown.lower()
    missing = [cmd for cmd in ctx.entry_points if cmd.lower() not in lowered]
    if not missing:
        return []
    return [
        Finding(
            "entry_point_coverage",
            f"Document the declared command(s) in a usage section: {', '.join(missing)}.",
        )
    ]


def _internal_leakage(markdown: str, ctx: ReadmeContext) -> list[Finding]:
    """Flag internal modules the draft surfaced as a section heading.

    Args:
        markdown: The generated README markdown.
        ctx: The run context carrying the internal module names.

    Returns:
        One finding listing every internal module used as a heading, else empty.
    """
    headings = [line.lstrip("#").strip().lower() for line in markdown.splitlines() if line.lstrip().startswith("#")]
    leaked = [
        name
        for name in ctx.internal_modules
        if name and any(re.search(rf"\b{re.escape(name.lower())}\b", h) for h in headings)
    ]
    if not leaked:
        return []
    return [
        Finding(
            "internal_leakage",
            f"Remove section heading(s) for internal module(s): {', '.join(sorted(set(leaked)))}.",
        )
    ]


def findings_as_feedback(findings: list[Finding]) -> str:
    """Fold quality findings into one feedback note the generator can act on.

    Args:
        findings: The problems found in the prior draft.

    Returns:
        A single instruction block listing every fix to apply.
    """
    fixes = "\n".join(f"- {f.detail}" for f in findings)
    return f"Fix these quality issues from the previous draft:\n{fixes}"
