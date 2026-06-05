"""Verifies generated README drafts against formatting and wording guidelines."""

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
    """Analyze a markdown draft to flag code fences, marketing terminology, and missing commands.

    Args:
        markdown: The generated README markdown text.
        project_name: The canonical name of the project.
        entry_points: Command entry points that must be documented.

    Returns:
        A list of identified style or content issues.
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
    """Flag any command-line entry point that is not mentioned in the markdown draft.

    Args:
        markdown: The generated README markdown text.
        entry_points: Declared entry points for command execution.

    Returns:
        A list of findings for any undocumented command.
    """
    lowered = markdown.lower()
    missing = [cmd for cmd in entry_points if cmd.lower() not in lowered]
    if not missing:
        return []
    return [Finding("entry_point_coverage", f"Document the declared command(s) in a usage section: {', '.join(missing)}.")]


def findings_as_feedback(findings: list[Finding]) -> str:
    """Aggregate quality findings into a single feedback block for the revision phase.

    Args:
        findings: A list of discovered quality issues.

    Returns:
        A markdown instruction block detailing the corrections.
    """
    fixes = "\n".join(f"- {f.detail}" for f in findings)
    return f"Fix these quality issues from the previous draft:\n{fixes}"
