"""Establishes the main docstring generation pipeline, managing caches, checkpoints, generation, and user reviews."""

import asyncio
import time
from pathlib import Path

from langchain_core.runnables import RunnableConfig

from docspatch.checkpoints import make_run_id
from docspatch.checkpoints.ledger import TokenLedger
from docspatch.checkpoints.runs import RunSummary, now_iso, write_run_summary
from docspatch.checkpoints.saver import docs_db_path, open_checkpoint_saver
from docspatch.llm import TokenUsage, tier_info
from docspatch.llm.pricing import actual_cost
from docspatch.manifest import ChangeManifest
from docspatch.pipelines.docs.context import (
    GraphContext,
    ReviewHandler,
    SwitchHandler,
    load_metadata,
)
from docspatch.pipelines.docs.finalize_graph import drive_finalize
from docspatch.pipelines.docs.flags import RunFlags, resolve_remarks
from docspatch.pipelines.docs.generate_graph import run_generation
from docspatch.pipelines.docs.generator import DocstringGenerator
from docspatch.pipelines.docs.plan_graph import batch_targets, build_plan_graph
from docspatch.pipelines.docs.state import DocsResult, FinalizeResult, GeneratedDoc, PlanState
from docspatch.pipelines.fanout import load_state
from docspatch.ui import Prompter, cache_hit_row, console, cost_rows, progress_bar, render_summary
from docspatch.ui.retry_display import RetryDisplay
from docspatch.utils.logging import get_logger
from docspatch.utils.secrets import scrub

log = get_logger("docs.pipeline")

MANIFEST_PIPELINE = "docs"


def scrub_for_summary(exc: BaseException) -> str:
    """Format an exception as a safe string by stripping out API keys and sensitive project secrets.

    Args:
        exc: The exception instance caught during the run.

    Returns:
        A sanitized string representation of the exception.
    """
    return scrub(f"{type(exc).__name__}: {exc}")


def _render_docs_summary(
    outcome: FinalizeResult,
    *,
    usage: TokenUsage,
    provider: str,
    tier: str,
    elapsed: float,
    cache_hits: int,
    scanned: int,
) -> None:
    """Write a summary table to the console detailing processed files, function counts, costs, and elapsed time.

    Args:
        outcome: The final results of the documentation commit step.
        usage: Aggregate tokens spent during generation.
        provider: Name of the language model provider used.
        tier: Configured pricing tier of the model.
        elapsed: Duration of the documentation pipeline in seconds.
        cache_hits: Number of unchanged files loaded from cache.
        scanned: Total files inspected during planning.
    """
    model = tier_info(provider, tier).model
    if outcome.aborted:
        rows = [
            ("Model", f"{model} ({provider})"),
            *cost_rows(usage, provider, tier, sunk=True),
            ("Elapsed", f"{elapsed:.1f}s"),
        ]
        render_summary("Docs run aborted — nothing written", rows, border_style="yellow")
        return
    rows = [
        ("Model", f"{model} ({provider})"),
        ("Files", str(len(outcome.committed))),
        ("Functions", str(outcome.fn_count)),
        ("Module docstrings", str(outcome.module_count)),
        ("Skipped files", str(len(outcome.skipped))),
        cache_hit_row(cache_hits, scanned),
        *cost_rows(usage, provider, tier),
        ("Elapsed", f"{elapsed:.1f}s"),
    ]
    render_summary("Docs run complete", rows, border_style="green")


async def run_docs(
    paths: list[Path],
    generator: DocstringGenerator,
    *,
    tone: str,
    repo_root: Path,
    flags: RunFlags | None = None,
    batch_token_limit: int,
    concurrency_limit: int,
    provider: str,
    tier: str,
    call_timeout: float = 120.0,
    prompter: Prompter | None = None,
    auto_confirm: bool = False,
    run_id: str | None = None,
    switch_handler: SwitchHandler | None = None,
    retry_display: RetryDisplay | None = None,
    review_handler: ReviewHandler | None = None,
) -> DocsResult:
    """Run the end-to-end docstring pipeline: plan, generate, review, and commit.

    Args:
        paths: List of files and directories to generate docstrings for.
        generator: The docstring generator instance executing the generation.
        tone: Stylistic guidelines or persona for the output docstrings.
        repo_root: Root path of the repository being analyzed.
        flags: Control options like update overrides and remark styling.
        batch_token_limit: Max total token count allowed in a single LLM request.
        concurrency_limit: Maximum number of parallel network requests allowed.
        provider: Target LLM provider API name.
        tier: Targeted model quality tier.
        call_timeout: Connection and response timeout for LLM calls in seconds.
        prompter: Interface to prompt users for approval.
        auto_confirm: Skip confirmation prompts before starting generation.
        run_id: Unique identifier for tracking this execution session.
        switch_handler: Handler invoked on model switches.
        retry_display: Interface to track retry status on the progress bar.
        review_handler: Interactive review session orchestrator.

    Returns:
        DocsResult summarizing execution stats, documented target counts, and any errors.

    Raises:
        BaseException: An unhandled error aborts the generation process.
    """
    flags = flags or RunFlags()
    rid = run_id or make_run_id()
    log.debug("run_docs: run_id=%s paths=%d provider=%s tier=%s", rid, len(paths), provider, tier)
    started = time.monotonic()
    db_path = docs_db_path(repo_root)
    checkpoint_dir = db_path.parent
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    ledger = TokenLedger(checkpoint_dir, rid)

    root = repo_root.resolve()
    rel_paths = sorted(p.resolve().relative_to(root).as_posix() for p in paths)
    manifest = ChangeManifest(repo_root)
    # Baseline stamps drive the planner's fast-skip; recompute + commit on success.
    prev_stamps = manifest.stamps(MANIFEST_PIPELINE)

    def record_state(committed: set[str], target_files: set[str]) -> None:
        # Record a file only when it is unchanged this run or was written. A file
        # that had targets but went unwritten (declined or skipped) is left out, so
        # the next run re-detects it instead of fast-skipping undocumented work.
        keep = [p for p in rel_paths if p not in target_files or p in committed]
        hashes, stamps = manifest.compute_state(MANIFEST_PIPELINE, root, keep)
        manifest.commit(MANIFEST_PIPELINE, hashes, stamps)
        log.debug("recorded docs manifest: %d/%d path(s) (committed=%d)", len(keep), len(rel_paths), len(committed))

    summary = RunSummary(
        run_id=rid,
        command="docs",
        provider=provider,
        tier=tier,
        model=tier_info(provider, tier).model,
        started_at=now_iso(),
        flags={
            "update": flags.update,
            "no_ignore": flags.no_ignore,
            "remarks": bool(flags.remarks),
        },
    )
    write_run_summary(repo_root, summary)

    ctx = GraphContext(
        generator=generator,
        sem=asyncio.Semaphore(concurrency_limit),
        repo_root=repo_root,
        tone=tone,
        prev_stamps=prev_stamps,
        provider=provider,
        tier=tier,
        prompter=prompter,
        auto_confirm=auto_confirm,
        batch_token_limit=batch_token_limit,
        run_id=rid,
        interactive=review_handler is not None,
        call_timeout=call_timeout,
        ledger=ledger,
    )

    def finalize(status: str) -> None:
        summary.ended_at = now_iso()
        summary.exit_status = status
        usage_now = ledger.totals()
        summary.input_tokens = usage_now.input_tokens
        summary.output_tokens = usage_now.output_tokens
        summary.cost_total = actual_cost(provider, tier, usage_now.input_tokens, usage_now.output_tokens).total
        write_run_summary(repo_root, summary)

    try:
        async with open_checkpoint_saver(db_path) as saver:
            config: RunnableConfig = {"configurable": {"thread_id": rid}}
            existing = await load_state(saver, config)
            is_resume = bool(existing.get("generated") or existing.get("completed_batches"))

            # Remarks live on the generator, not in graph state — a resumed run
            # restores them from checkpoint metadata, overriding only on request.
            prior_remarks = (await load_metadata(saver, config)).get("remarks") if is_resume else None
            remarks = resolve_remarks(is_resume=is_resume, prior=prior_remarks, requested=flags.remarks, prompter=prompter)
            generator.remarks = remarks
            config = {"configurable": {"thread_id": rid}, "metadata": {"remarks": remarks}}

            plan_initial: PlanState = {"paths": paths, "repo_root": repo_root, "tone": tone, "flags": flags}
            if is_resume:
                plan_initial["confirmed"] = True
            plan_state = await build_plan_graph(ctx).ainvoke(plan_initial)

            if not plan_state.get("targets"):
                await saver.adelete_thread(rid)
                record_state(committed=set(), target_files=set())
                finalize("success")
                ledger.delete()
                return DocsResult(functions_documented=0, files_documented=0, batches=0)
            if not plan_state.get("confirmed"):
                finalize("declined")
                ledger.delete()
                return DocsResult(functions_documented=0, files_documented=0, batches=0, confirmed=False)

            cache_hits = plan_state.get("cache_hits", 0)
            scanned = cache_hits + len(plan_state["targets"])
            target_files = {t.rel for t in plan_state["targets"]}
            summary.files_scanned = scanned
            log.debug("plan: %d target(s), %d cache hit(s), resume=%s", len(plan_state["targets"]), cache_hits, is_resume)

            # Only generate targets without a docstring already in the checkpoint —
            # a resumed run reuses what the prior run produced, no LLM re-call.
            done_keys = {(g.rel, g.qualname) for g in existing.get("generated", [])}
            missing = [t for t in plan_state["targets"] if (t.rel, t.qualname) not in done_keys]
            if is_resume:
                console.print(f"[dim]Resuming run {rid} · {len(done_keys)} done · {len(missing)} remaining[/dim]")

            if missing:
                offset = max(existing.get("completed_batches", []), default=-1) + 1
                batches = batch_targets(ctx, missing, offset)
                log.debug("generating %d docstring(s) across %d batch(es)", len(missing), len(batches))
                with progress_bar(total=len(missing), description="Generating docstrings") as bar:
                    ctx.advance = bar
                    if retry_display is not None:
                        retry_display.bind(bar.set_status)
                    try:
                        await run_generation(ctx, saver, config, batches, switch_handler, bar)
                    finally:
                        if retry_display is not None:
                            retry_display.unbind()
                    ctx.advance = None

            final = await load_state(saver, config)
            entries: list[GeneratedDoc] = list(final.get("generated", []))
            batch_count = len(plan_state.get("batches", []))

            if not entries:
                await saver.adelete_thread(rid)
                finalize("success")
                ledger.delete()
                return DocsResult(functions_documented=0, files_documented=0, batches=batch_count)

            outcome = await drive_finalize(ctx, saver, review_handler, entries)
            log.debug("finalize: committed=%d aborted=%s error=%s", len(outcome.committed), outcome.aborted, bool(outcome.error))
            await saver.adelete_thread(rid)
            usage = ledger.totals()
            elapsed = time.monotonic() - started
            if outcome.aborted:
                await saver.adelete_thread(f"review-{rid}")
                _render_docs_summary(
                    outcome,
                    usage=usage,
                    provider=provider,
                    tier=tier,
                    elapsed=elapsed,
                    cache_hits=cache_hits,
                    scanned=scanned,
                )
                summary.files_skipped = list(outcome.skipped)
                finalize("aborted")
                ledger.delete()
                return DocsResult(functions_documented=0, files_documented=0, batches=batch_count, aborted=True)

            _render_docs_summary(
                outcome,
                usage=usage,
                provider=provider,
                tier=tier,
                elapsed=elapsed,
                cache_hits=cache_hits,
                scanned=scanned,
            )
            summary.files_documented = list(outcome.committed)
            summary.files_skipped = list(outcome.skipped)
            summary.functions_documented = outcome.fn_count
            if outcome.error:
                summary.errors.append(outcome.error)
            else:
                # Disk writes succeeded; persist the new baseline so the next run
                # fast-skips them. A failed run rolls back, so it records nothing.
                record_state(committed=set(outcome.committed), target_files=target_files)
            finalize("error" if outcome.error else "success")
            ledger.delete()

        return DocsResult(
            functions_documented=outcome.fn_count,
            files_documented=len(outcome.committed),
            batches=batch_count,
            modules_documented=outcome.module_count,
            skipped_files=len(outcome.skipped),
            error=outcome.error,
        )
    except BaseException as exc:
        summary.errors.append(scrub_for_summary(exc))
        log.debug("run_docs failed: %s", scrub_for_summary(exc))
        finalize("error")
        raise
