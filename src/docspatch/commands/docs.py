"""``dp docs`` — generate docstrings for undocumented functions."""

import asyncio
from pathlib import Path

import typer

from docspatch.cache import DocsCache
from docspatch.checkpoints.janitor import start_janitor
from docspatch.checkpoints.runs import list_incomplete_runs, pick_last_run
from docspatch.llm import LLMClient, tier_for_model
from docspatch.pipelines.docs import run_docs
from docspatch.pipelines.docs.flags import RunFlags, preview_check, validate_run_flags
from docspatch.pipelines.docs.generator import LLMDocstringGenerator
from docspatch.ui import Prompter, QuestionaryPrompter, console
from docspatch.ui.retry_display import RetryDisplay
from docspatch.ui.review_panel import prompt_conflict, review_session
from docspatch.utils.config import default_store
from docspatch.utils.ignore import load_docsignore
from docspatch.utils.lockfile import run_lock
from docspatch.utils.logging import get_logger
from docspatch.utils.scope import resolve_scope
from docspatch.utils.selection import ensure_configured
from docspatch.utils.switcher import offer_switch

log = get_logger("docs")

PATHS_ARG = typer.Argument(None, help="One or more .py files or directories (repo-relative).")
NO_IGNORE_OPTION = typer.Option(False, "--no-ignore", help="Skip .gitignore + .docsignore filtering for explicit paths and dirs.")
CHECK_OPTION = typer.Option(False, "--check", help="Preview undocumented functions and cost; write nothing.")
UPDATE_OPTION = typer.Option(False, "--update", help="Regenerate docstrings even where the source is unchanged.")
REMARKS_OPTION = typer.Option(None, "--remarks", help="Extra instruction added to every docstring prompt.")
RESUME_OPTION = typer.Option(False, "--resume", help="Resume the most recent interrupted run.")


def run(flags: RunFlags, prompter: Prompter | None = None) -> None:
    """Document every undocumented function across ``flags.paths``.

    Holds the per-repo run lock for the whole pipeline.
    """
    validate_run_flags(flags)
    repo_root = Path.cwd()
    with run_lock(repo_root):
        ignore = load_docsignore(repo_root)
        # No explicit paths -> document the whole repo.
        scope = list(flags.paths) or [Path(".")]
        targets = resolve_scope(scope, repo_root, ignore=ignore, no_ignore=flags.no_ignore)
        log.debug("resolved scope: %d target file(s)", len(targets))

        store = default_store(repo_root)
        p = prompter or QuestionaryPrompter()
        selections = ensure_configured(store, p)
        cfg = store.read()
        tier = tier_for_model(selections.provider, selections.generator_model)
        log.debug("config loaded: provider=%s tier=%s", selections.provider, tier)

        cache = DocsCache(repo_root)
        if flags.check:
            needs_docs = preview_check(targets, repo_root, cache, selections.provider, tier)
            raise typer.Exit(1 if needs_docs else 0)

        run_id = None
        if flags.resume:
            run_id = pick_last_run(asyncio.run(list_incomplete_runs(repo_root)))
            console.print(f"[dim]Resuming run {run_id}[/dim]")

        retry_display = RetryDisplay()
        client = LLMClient(
            provider=selections.provider,
            api_key=selections.api_key,
            generator_tier=tier,
            retry_cb=retry_display,
        )
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

        async def handle_exhaustion(current: LLMDocstringGenerator) -> LLMDocstringGenerator | None:
            switched = await offer_switch(
                store,
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
                tone=selections.tone,
                repo_root=repo_root,
                flags=flags,
                batch_token_limit=cfg.batch_token_limit.value,
                concurrency_limit=cfg.concurrency_limit.value,
                call_timeout=cfg.call_timeout.value,
                provider=selections.provider,
                tier=tier,
                cache=cache,
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


async def run_with_janitor(*args: object, repo_root: Path, **kwargs: object):
    """Fire the once-per-day sweep, then run the docs pipeline."""
    start_janitor(repo_root)
    return await run_docs(*args, repo_root=repo_root, **kwargs)  # type: ignore[arg-type]
