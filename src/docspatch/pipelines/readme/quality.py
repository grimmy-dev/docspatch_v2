"""Deterministic quality checks that gate a README draft before review."""

import re
from dataclasses import dataclass

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


def inspect_readme(markdown: str, *, project_name: str | None, entry_points: tuple[str, ...]) -> list[Finding]:
    """Report quality problems in a README draft.

    Args:
        markdown: The generated README markdown.
        project_name: The authoritative project name, or null for a subpackage.
        entry_points: Declared entry-point commands the README must document.

    Returns:
        Every quality problem found; an empty list means the draft passes.
    """
    findings: list[Finding] = []

    if markdown.strip().startswith("```"):
        findings.append(Finding("fenced", "Remove the surrounding code fence; output the markdown document itself."))

    if not any(line.startswith("# ") for line in markdown.splitlines()):
        findings.append(Finding("no_title", "Add a single top-level title (a line starting with '# ')."))

    hits = sorted(set(_MARKETING_RE.findall(markdown.lower())))
    if hits:
        joined = ", ".join(hits)
        findings.append(Finding("marketing", f"Drop marketing language ({joined}); state concretely what the project does."))

    if project_name and project_name.lower() not in markdown.lower():
        findings.append(Finding("missing_name", f"Name the project ('{project_name}') in the README."))

    findings += _entry_point_coverage(markdown, entry_points)
    return findings


def _entry_point_coverage(markdown: str, entry_points: tuple[str, ...]) -> list[Finding]:
    """Flag any declared entry-point command the README never mentions.

    A no-op for a project that declares no scripts (a library or a service), so
    only repos that actually ship commands are held to this bar.

    Args:
        markdown: The generated README markdown.
        entry_points: The declared entry-point commands.

    Returns:
        One finding per missing command, empty when all are covered.
    """
    lowered = markdown.lower()
    missing = [cmd for cmd in entry_points if cmd.lower() not in lowered]
    if not missing:
        return []
    return [Finding("entry_point_coverage", f"Document the declared command(s) in a usage section: {', '.join(missing)}.")]


def findings_as_feedback(findings: list[Finding]) -> str:
    """Fold quality findings into one feedback note the generator can act on.

    Args:
        findings: The problems found in the prior draft.

    Returns:
        A single instruction block listing every fix to apply.
    """
    fixes = "\n".join(f"- {f.detail}" for f in findings)
    return f"Fix these quality issues from the previous draft:\n{fixes}"
