"""Generate a path-scoped README through the agent context pipeline."""

import asyncio
from dataclasses import dataclass
from pathlib import Path

import typer

from docspatch.llm import tier_for_model
from docspatch.ui import Prompter, QuestionaryPrompter, console, status
from docspatch.ui.prompter import is_interactive
from docspatch.utils.config import default_store
from docspatch.utils.errors import ConfigError, ReadmeError
from docspatch.utils.lockfile import run_lock
from docspatch.utils.logging import get_logger
from docspatch.utils.scope import ensure_exists, ensure_inside_repo, ensure_relative
from docspatch.utils.selection import ensure_configured

log = get_logger("readme")

PATH_ARG = typer.Argument(None, help="Directory to scope the README to (repo-relative). Omit for the repo root.")
UPDATE_OPTION = typer.Option(
    False, "--update", help="Rewrite the README from scratch instead of refreshing it in place."
)
CHECK_OPTION = typer.Option(False, "--check", help="Report whether the README is stale; write nothing, no model calls.")
REMARKS_OPTION = typer.Option(None, "--remarks", help="Extra instruction added to the generation prompt.")

README_NAME = "README.md"

# Flag pairs that cannot be combined, with the hint shown on conflict.
_CONFLICTS = (
    ("check", "update", "--check only reports staleness; drop it to rewrite."),
    ("check", "remarks", "--remarks steers generation; --check generates nothing."),
)


@dataclass(frozen=True)
class ReadmeFlags:
    """Resolved CLI inputs for a README run."""

    path: Path | None = None
    update: bool = False
    check: bool = False
    remarks: str | None = None


def validate_flags(flags: ReadmeFlags) -> None:
    """Reject mutually exclusive flag combinations.

    Args:
        flags: The resolved run inputs.

    Raises:
        ConfigError: Two conflicting flags are active together.
    """
    active = {"check": flags.check, "update": flags.update, "remarks": flags.remarks is not None}
    for a, b, hint in _CONFLICTS:
        if active[a] and active[b]:
            raise ConfigError.conflicting_flags(a, b, hint)


def resolve_target(path: Path | None, repo_root: Path) -> tuple[str, Path]:
    """Map the path argument to a directory scope and a README output location.

    Args:
        path: The directory argument, or null for the repo root.
        repo_root: The repository root.

    Returns:
        The repo-relative scope and the README path to write.

    Raises:
        PathError: The path is absolute, missing, or outside the repo.
        ReadmeError: The path points at a file rather than a directory.
    """
    root = repo_root.resolve()
    if path is None:
        return ".", root / README_NAME
    rel = ensure_relative(path, root)
    abs_path = (root / rel).resolve()
    ensure_exists(path, abs_path)
    ensure_inside_repo(abs_path, root)
    if not abs_path.is_dir():
        raise ReadmeError.not_a_directory(rel)
    return rel, abs_path / README_NAME


def run_check(repo_root: Path, scope: str, out_path: Path) -> bool:
    """Report README freshness from the change manifest, no model calls.

    Args:
        repo_root: The repository root.
        scope: The repo-relative scope.
        out_path: The README path.

    Returns:
        True when the README is fresh (up to date).
    """
    from docspatch.pipelines.readme.pipeline import is_fresh, scope_state

    with status("Checking for changes…"):
        state = scope_state(repo_root, scope)
    rel = out_path.relative_to(repo_root.resolve()).as_posix()
    if is_fresh(state, out_path):
        console.print(f"[green]✓[/green] {rel} is up to date.")
        return True
    if not out_path.exists():
        console.print(f"[yellow]{rel} does not exist — it needs generation.[/yellow]")
    else:
        cs = state.change_set
        console.print(f"[yellow]{rel} may be stale — {len(cs.changed)} changed, {len(cs.removed)} removed file(s).[/yellow]")
    return False


def _with_update(flags: ReadmeFlags) -> str | None:
    """Fold the ``--update`` flag into the run remark as a restructure instruction.

    The pipeline always treats the existing README as the baseline and voice
    reference; ``--update`` simply licenses free restructuring on top of that.

    Args:
        flags: The resolved run inputs.

    Returns:
        The combined remark, or null when neither remark nor update is set.
    """
    if not flags.update:
        return flags.remarks
    note = (
        "Rewrite the README freely: you may restructure, reorder, and reword sections for clarity, "
        "while preserving the content of every hand-written section."
    )
    return f"{flags.remarks}\n{note}" if flags.remarks else note


def run(flags: ReadmeFlags, prompter: Prompter | None = None) -> None:
    """Generate or check a README for the requested scope.

    Args:
        flags: Resolved run inputs.
        prompter: Interface for user input.
    """
    validate_flags(flags)
    repo_root = Path.cwd()
    scope, out_path = resolve_target(flags.path, repo_root)
    p = prompter or QuestionaryPrompter()
    log.debug("resolved scope=%s readme=%s", scope, out_path.name)

    if flags.check:
        fresh = run_check(repo_root.resolve(), scope, out_path)
        if fresh or not is_interactive() or not p.confirm("Generate now?"):
            raise typer.Exit(0 if fresh else 1)
        console.print("[dim]Generating README…[/dim]")

    # Deferred so a bare `dp`/`--help`/`--check` never pays the provider-SDK cost.
    with status("Starting up…"):
        from docspatch.llm import LLMClient, validate_api_key
        from docspatch.pipelines.readme.generator import LLMReadmeGenerator
        from docspatch.pipelines.readme.pipeline import generate_readme

    remarks = _with_update(flags)
    store = default_store(repo_root)
    selections = ensure_configured(store, p, validate_api_key)
    tier = tier_for_model(selections.provider, selections.generator_model)
    log.debug("config loaded: provider=%s tier=%s", selections.provider, tier)

    with run_lock(repo_root):
        with status(f"Connecting to {selections.provider}…"):
            analysis_client = LLMClient(provider=selections.provider, api_key=selections.api_key, generator_tier="fast")
            gen_client = LLMClient(provider=selections.provider, api_key=selections.api_key, generator_tier=tier)
            connected = analysis_client.validate_key()
        if not connected:
            console.print(f"[red]✗[/red] Could not connect to {selections.provider}. Check your API key with `dp init --reconfigure`.")
            raise typer.Exit(1)
        console.print(f"[green]✓[/green] Connected to {selections.provider}.")
        generator = LLMReadmeGenerator(gen_client)
        log.debug("starting readme generation")
        result = asyncio.run(
            generate_readme(
                repo_root,
                scope,
                out_path,
                analysis_client=analysis_client,
                generator=generator,
                prompter=p,
                remarks=remarks,
                provider=selections.provider,
                tier=tier,
            )
        )
    log.debug("readme finished: written=%s", result.written)
