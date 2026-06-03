"""Generate a path-scoped README from scout summaries."""

import asyncio
from dataclasses import dataclass
from pathlib import Path

import typer

from docspatch.cache import ScoutCache
from docspatch.llm import tier_for_model
from docspatch.pipelines.readme.check import CHECK_GENERATE, CHECK_STALE, run_check
from docspatch.schemas import RunSettings
from docspatch.ui import Prompter, QuestionaryPrompter, console, status
from docspatch.utils.config import default_store
from docspatch.utils.errors import ConfigError, ReadmeError
from docspatch.utils.lockfile import run_lock
from docspatch.utils.logging import get_logger
from docspatch.utils.scope import ensure_exists, ensure_inside_repo, ensure_relative
from docspatch.utils.selection import ensure_configured

log = get_logger("readme")

PATH_ARG = typer.Argument(None, help="Directory to scope the README to (repo-relative). Omit for the repo root.")
UPDATE_OPTION = typer.Option(False, "--update", help="Full rewrite of the README (the default behaviour).")
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


def run(flags: ReadmeFlags, prompter: Prompter | None = None) -> None:
    """Generate or check a README for the requested scope.

    Args:
        flags: Resolved run inputs.
        prompter: Interface for user input.
    """
    validate_flags(flags)
    repo_root = Path.cwd()
    scope, out_path = resolve_target(flags.path, repo_root)
    readme_rel = out_path.relative_to(repo_root.resolve()).as_posix()
    p = prompter or QuestionaryPrompter()
    log.debug("resolved scope=%s readme=%s", scope, readme_rel)

    if flags.check:
        action = run_check(repo_root.resolve(), scope, readme_rel, p)
        log.debug("check action: %s", action)
        if action == CHECK_GENERATE:
            console.print("[dim]Generating README…[/dim]")
        else:
            raise typer.Exit(1 if action == CHECK_STALE else 0)

    # Deferred so a bare `dp`/`--help`/`--check` never pays the provider-SDK cost.
    with status("Starting up…"):
        from docspatch.llm import LLMClient, validate_api_key
        from docspatch.pipelines.readme.generator import LLMReadmeGenerator
        from docspatch.pipelines.readme.pipeline import ensure_scope_fresh, generate_readme

    store = default_store(repo_root)
    selections = ensure_configured(store, p, validate_api_key)
    settings = RunSettings.from_config(store.read())
    tier = tier_for_model(selections.provider, selections.generator_model)
    log.debug("config loaded: provider=%s tier=%s", selections.provider, tier)

    with run_lock(repo_root):
        ctx_store = ScoutCache(repo_root)
        ensure_scope_fresh(repo_root, ctx_store, store, selections.provider, selections.api_key, scope, p)
        client = LLMClient(provider=selections.provider, api_key=selections.api_key, generator_tier=tier)
        generator = LLMReadmeGenerator(client, batch_token_limit=settings.batch_token_limit)
        log.debug("starting readme generation")
        result = asyncio.run(
            generate_readme(
                repo_root,
                scope,
                out_path,
                generator=generator,
                prompter=p,
                remarks=flags.remarks,
                provider=selections.provider,
                tier=tier,
            )
        )
    log.debug("readme finished: written=%s", result.written)
