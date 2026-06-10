"""Combined README + docstring staleness check for pre-commit use; reads only, no LLM, no config."""

from pathlib import Path

import typer

from docspatch.ui import console
from docspatch.utils.errors import PathError

DOCS_PIPELINE = "docs"
README_NAME = "README.md"


def run() -> None:
    """Report README and docstring staleness, exiting non-zero when either is stale.

    Raises:
        Exit: Always exits 1 if anything is stale, 0 when both are fresh.
    """
    stale = report(Path.cwd().resolve())
    raise typer.Exit(1 if stale else 0)


def report(repo_root: Path) -> bool:
    """Print README and docstring staleness without exiting.

    Args:
        repo_root: The repository root.

    Returns:
        True when the README or any docstring is stale.
    """
    readme_stale = check_readme(repo_root)
    docs_stale = check_docs(repo_root)
    return readme_stale or docs_stale


def check_readme(repo_root: Path) -> bool:
    """Compare the repository scope against README.md and report whether it is stale.

    Args:
        repo_root: The repository root.

    Returns:
        True when the README is missing or out of date.
    """
    from docspatch.pipelines.readme.pipeline import is_fresh, scope_state

    out_path = repo_root / README_NAME
    try:
        state = scope_state(repo_root, ".")
    except PathError:
        # No Python sources to compare the README against — nothing to flag.
        console.print("[green]✓[/green] No Python sources to compare README.md against.")
        return False
    if is_fresh(state, out_path):
        console.print("[green]✓[/green] README.md is up to date.")
        return False
    if not out_path.exists():
        console.print("[yellow]README.md is missing — run [/yellow]dp readme[yellow] to generate it.[/yellow]")
    else:
        cs = state.change_set
        console.print(
            f"[yellow]README.md may be stale — {len(cs.changed)} changed, {len(cs.removed)} removed file(s). "
            f"Run [/yellow]dp readme[yellow] to refresh it.[/yellow]"
        )
    return True


def check_docs(repo_root: Path) -> bool:
    """Count undocumented functions in changed files and report whether docs are stale.

    Args:
        repo_root: The repository root.

    Returns:
        True when any function still needs a docstring.
    """
    from docspatch.manifest import ChangeManifest
    from docspatch.pipelines.docs.planner import collect_targets
    from docspatch.utils.ignore import load_docsignore
    from docspatch.utils.scope import discover_targets

    try:
        targets = discover_targets([Path(".")], repo_root, ignore=load_docsignore(repo_root))
    except PathError:
        # No Python files in scope — nothing to document.
        console.print("[green]✓[/green] No Python files to document.")
        return False

    prev_stamps = ChangeManifest(repo_root).stamps(DOCS_PIPELINE)
    result = collect_targets(targets, repo_root, prev_stamps)
    if not result.targets:
        console.print("[green]✓[/green] All Python files documented.")
        return False
    files = len({t.rel for t in result.targets})
    console.print(
        f"[yellow]{len(result.targets)} function(s) across {files} file(s) need docstrings. "
        f"Run [/yellow]dp docs[yellow] to document them.[/yellow]"
    )
    return True
