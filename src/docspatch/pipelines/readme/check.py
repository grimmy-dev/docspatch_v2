"""Git-based staleness checks for identifying stale or uncommitted READMEs."""

import re
from dataclasses import dataclass
from pathlib import Path

from docspatch.ui import Prompter, console
from docspatch.ui.prompter import is_interactive
from docspatch.utils.git import Commit, GitReader
from docspatch.utils.logging import get_logger

log = get_logger("readme.check")

# Subjects of these conventional types rarely change a README's prose.
_LIKELY_NOOP_TYPES = frozenset({"docs", "fix", "chore", "test", "style"})
_CONVENTIONAL_RE = re.compile(r"^(?P<type>\w+)(\([^)]*\))?!?:")

CHECK_CURRENT = "current"
CHECK_SKIP = "skip"
CHECK_STALE = "stale"
CHECK_GENERATE = "generate"


@dataclass(frozen=True)
class CommitHint:
    """A commit since the README's last touch, with a no-op likelihood hint."""

    commit: Commit
    likely_noop: bool


@dataclass(frozen=True)
class StaleReport:
    """The staleness verdict for one scoped README."""

    readme_rel: str
    committed: bool
    hints: list[CommitHint]

    @property
    def stale(self) -> bool:
        """Report whether the README needs regeneration.

        Returns:
            True when the README is uncommitted or trailing later code commits.
        """
        return (not self.committed) or bool(self.hints)


def py_pathspec(scope: str) -> str:
    """Build a git glob pathspec for scoped Python files.

    Args:
        scope: The repo-relative directory; '.' covers the whole repo.

    Returns:
        A ':(glob)' pathspec matching '*.py' under the scope.
    """
    if scope in {".", "", "./"}:
        return ":(glob)**/*.py"
    return f":(glob){scope.rstrip('/')}/**/*.py"


def likely_noop(subject: str) -> bool:
    """Report whether a commit subject suggests no README change is needed.

    Args:
        subject: The commit subject line.

    Returns:
        True when the conventional type is one that rarely affects a README.
    """
    match = _CONVENTIONAL_RE.match(subject)
    if match is None:
        return False
    return match.group("type").lower() in _LIKELY_NOOP_TYPES


def build_report(repo_root: Path, scope: str, readme_rel: str) -> StaleReport:
    """Compute the staleness report for a scoped README from git history.

    Args:
        repo_root: The repository root.
        scope: The repo-relative directory the README covers.
        readme_rel: The README path relative to the repository root.

    Returns:
        The staleness report; uncommitted READMEs carry no commit list.
    """
    git = GitReader(repo_root)
    ref = git.last_commit_touching([readme_rel])
    if ref is None:
        log.debug("staleness: %s has no commit history — needs generation", readme_rel)
        return StaleReport(readme_rel=readme_rel, committed=False, hints=[])
    commits = git.commits_since(ref, [py_pathspec(scope)])
    log.debug("staleness: %s last touched at %s, %d later code commit(s)", readme_rel, ref[:7], len(commits))
    hints = [CommitHint(commit=c, likely_noop=likely_noop(c.subject)) for c in commits]
    return StaleReport(readme_rel=readme_rel, committed=True, hints=hints)


def render_report(report: StaleReport) -> None:
    """Print the staleness verdict and the commits behind it.

    Args:
        report: The computed staleness report.
    """
    if not report.committed:
        console.print(f"[yellow]{report.readme_rel} is not committed — it needs generation.[/yellow]")
        return
    console.print(f"[yellow]{report.readme_rel} may be stale — {len(report.hints)} later code commit(s):[/yellow]")
    for hint in report.hints:
        sha = hint.commit.sha[:7]
        note = "  [dim](likely no README change)[/dim]" if hint.likely_noop else ""
        console.print(f"  [dim]{sha}[/dim] {hint.commit.subject}{note}")


def run_check(repo_root: Path, scope: str, readme_rel: str, prompter: Prompter) -> str:
    """Evaluate staleness, report it, and resolve the next action.

    Args:
        repo_root: The repository root.
        scope: The repo-relative directory the README covers.
        readme_rel: The README path relative to the repository root.
        prompter: Interface for user input.

    Returns:
        One of 'current', 'stale', 'skip', or 'generate'.
    """
    report = build_report(repo_root, scope, readme_rel)
    if not report.stale:
        console.print(f"[green]✓[/green] {report.readme_rel} is up to date.")
        return CHECK_CURRENT
    render_report(report)
    if not is_interactive():
        return CHECK_STALE
    action = prompter.select(
        "How should docspatch proceed?",
        {"Generate now": CHECK_GENERATE, "Skip (leave the README as is)": CHECK_SKIP},
    )
    return str(action)
