"""Run logic for parsing Python files, starting threads, and applying generated docstrings."""

import asyncio
from pathlib import Path

import typer

from docspatch.pipelines.docs.flags import RunFlags, preview_check, validate_run_flags
from docspatch.schemas import RunSettings
from docspatch.ui import Prompter, QuestionaryPrompter, console, status
from docspatch.ui.prompter import is_interactive
from docspatch.ui.retry_display import RetryDisplay
from docspatch.utils.ignore import load_docsignore
from docspatch.utils.lockfile import run_lock
from docspatch.utils.logging import get_logger
from docspatch.utils.scope import discover_targets
from docspatch.utils.session import client_for, load_session, verify_connection

log = get_logger("docs")

PATHS_ARG = typer.Argument(None, help="One or more .py files or directories (repo-relative).")
NO_IGNORE_OPTION = typer.Option(False, "--no-ignore", help="Skip .gitignore + .docsignore filtering for explicit paths and dirs.")
CHECK_OPTION = typer.Option(False, "--check", help="Preview undocumented functions and cost; write nothing.")
UPDATE_OPTION = typer.Option(
    False,
    "--update",
    help="Regenerate every module and top-level/method docstring, even unchanged ones. "
    "Functions nested inside other functions are not documented.",
)
REMARKS_OPTION = typer.Option(None, "--remarks", help="Extra instruction added to every docstring prompt.")
RESUME_OPTION = typer.Option(False, "--resume", help="Resume the most recent interrupted run.")


def run(flags: RunFlags, prompter: Prompter | None = None) -> None:
    """Generate and apply docstrings to undocumented functions in the specified paths.

    Args:
        flags: Command line configuration options and scope targets.
        prompter: UI interface for interactive prompts and review choices.

    Raises:
        Exit: A preview check fails or when committing the changes fails.
    """
    validate_run_flags(flags)
    repo_root = Path.cwd()
    with run_lock(repo_root):
        # Deferred so a bare `dp`/`--help` never pays the provider-SDK + libcst
        # + langgraph import cost; only a real docs run does, under this spinner.
        with status("Starting up…"):
            from docspatch.checkpoints.runs import list_incomplete_runs, pick_last_run
            from docspatch.pipelines.docs.generator import DocstringGenerator, LLMDocstringGenerator
            from docspatch.ui.review_panel import prompt_conflict, review_session
            from docspatch.utils.switcher import offer_switch

        # No explicit paths -> document the whole repo.
        scope = list(flags.paths) or [Path(".")]
        with status("Scanning files…"):
            ignore = load_docsignore(repo_root)
            targets = discover_targets(scope, repo_root, ignore=ignore, no_ignore=flags.no_ignore)
        log.debug("resolved scope: %d target file(s)", len(targets))

        p = prompter or QuestionaryPrompter()
        session = load_session(repo_root, p)
        settings = RunSettings.from_config(session.store.read())

        if flags.check:
            from docspatch.manifest import ChangeManifest

            prev_stamps = ChangeManifest(repo_root).stamps("docs")
            needs_docs = preview_check(targets, repo_root, prev_stamps, session.provider, session.tier)
            raise typer.Exit(1 if needs_docs else 0)

        run_id = None
        if flags.resume:
            run_id = pick_last_run(asyncio.run(list_incomplete_runs(repo_root)))
            console.print(f"[dim]Resuming run {run_id}[/dim]")
        else:
            run_id = offer_resume(repo_root, p)

        verify_connection(session)
        retry_display = RetryDisplay()
        client = client_for(session, retry_cb=retry_display)
        generator = LLMDocstringGenerator(client)

        def review_handler(payload: dict) -> dict:
            if payload.get("type") == "hash_mismatch":
                return prompt_conflict(p, payload["file"])
            return review_session(
                payload["entries"],
                repo_root=repo_root,
                prompter=p,
                allow_rerun=payload["allow_rerun"],
            )

        async def handle_exhaustion(current: DocstringGenerator) -> DocstringGenerator | None:
            switched = await offer_switch(
                session.store,
                p,
                current_provider=client.provider,
                current_model=client.generator_model,
                retry_cb=retry_display,
            )
            return LLMDocstringGenerator(switched.client, remarks=current.remarks) if switched else None

        log.debug("starting docs pipeline")
        result = asyncio.run(
            run_with_janitor(
                targets,
                generator,
                tone=session.selections.tone,
                repo_root=repo_root,
                flags=flags,
                batch_token_limit=settings.batch_token_limit,
                concurrency_limit=settings.concurrency_limit,
                call_timeout=settings.call_timeout,
                provider=session.provider,
                tier=session.tier,
                prompter=p,
                run_id=run_id,
                switch_handler=handle_exhaustion,
                retry_display=retry_display,
                review_handler=review_handler,
            )
        )

    log.debug(
        "pipeline finished: confirmed=%s aborted=%s documented=%d",
        result.confirmed,
        result.aborted,
        result.functions_documented,
    )
    # The run summary panel is rendered by the pipeline; the command only owns
    # the empty-run notice and the commit-error exit code.
    if not result.confirmed or result.aborted:
        return
    if result.error:
        console.print(f"[red]✗[/red] Commit failed: {result.error}")
        raise typer.Exit(1)
    if result.functions_documented == 0 and result.modules_documented == 0:
        console.print("[dim]Nothing to document. All functions already have docstrings.[/dim]")


def offer_resume(repo_root: Path, p: Prompter) -> str | None:
    """Resume an interrupted documentation run after user confirmation.

    Args:
        repo_root: Directory path to the local repository root.
        p: Prompting interface to ask the user.

    Returns:
        The unique identifier of the run to resume, or None if starting fresh.
    """
    from docspatch.checkpoints.runs import discard_incomplete_runs, list_incomplete_runs

    incomplete = asyncio.run(list_incomplete_runs(repo_root))
    if not incomplete:
        return None
    rid = incomplete[0]
    if not is_interactive():
        # Headless: never block; mention how to resume explicitly.
        console.print(f"[dim]Interrupted run {rid} found — pass --resume to continue it.[/dim]")
        return None
    if p.confirm(f"Resume interrupted run {rid}?", default=True):
        console.print(f"[dim]Resuming run {rid}[/dim]")
        return rid
    asyncio.run(discard_incomplete_runs(repo_root))
    return None


async def run_with_janitor(*args: object, repo_root: Path, **kwargs: object):
    """Run the documentation pipeline with a background janitor task clearing temporary checkpoints.

    Args:
        repo_root: Directory path of the target workspace.

    Returns:
        The pipeline run result containing stats and completion status.
    """
    from docspatch.checkpoints.janitor import start_janitor, vacuum_checkpoints
    from docspatch.pipelines.docs import run_docs

    # Hold a strong reference so the task is not GC'd before the sweep finishes.
    janitor = start_janitor(repo_root)
    try:
        return await run_docs(*args, repo_root=repo_root, **kwargs)  # type: ignore[arg-type]
    finally:
        await janitor
        # The pipeline's AsyncSqliteSaver is closed by now — safe to vacuum.
        # This runs after the summary panel, so surface it instead of going blank.
        with status("Tidying checkpoints…"):
            await asyncio.to_thread(vacuum_checkpoints, repo_root / ".docspatch" / "checkpoints")
