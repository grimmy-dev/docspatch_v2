"""Docs pipeline orchestrator.

Runs the plan graph, then generation, then the review → commit graph, against
a single ``AsyncSqliteSaver`` keyed by ``thread_id == run_id`` so a resumed run
reuses prior work without re-calling the LLM.
"""

import asyncio
import time
from pathlib import Path

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from docspatch.cache import DocsCache
from docspatch.checkpoints import make_run_id
from docspatch.checkpoints.ledger import TokenLedger
from docspatch.llm import TokenUsage, tier_info
from docspatch.pipelines.docs.context import (
    GraphContext,
    ReviewHandler,
    SwitchHandler,
    load_metadata,
    load_state,
)
from docspatch.pipelines.docs.finalize_graph import drive_finalize
from docspatch.pipelines.docs.flags import RunFlags, resolve_remarks
from docspatch.pipelines.docs.generate_graph import run_generation
from docspatch.pipelines.docs.generator import LLMDocstringGenerator
from docspatch.pipelines.docs.plan_graph import batch_targets, build_plan_graph
from docspatch.pipelines.docs.state import DocsResult, FinalizeResult, GeneratedDoc, PlanState
from docspatch.ui import Prompter, cache_hit_row, console, cost_rows, progress_bar, render_summary
from docspatch.ui.retry_display import RetryDisplay


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
    """Print the end-of-run panel: real tokens, cost, counts, cache-hit ratio."""
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
    generator: LLMDocstringGenerator,
    *,
    tone: str,
    repo_root: Path,
    flags: RunFlags | None = None,
    batch_token_limit: int,
    concurrency_limit: int,
    provider: str,
    tier: str,
    call_timeout: float = 120.0,
    cache: DocsCache | None = None,
    prompter: Prompter | None = None,
    auto_confirm: bool = False,
    run_id: str | None = None,
    switch_handler: SwitchHandler | None = None,
    retry_display: RetryDisplay | None = None,
    review_handler: ReviewHandler | None = None,
) -> DocsResult:
    """Run the docs pipeline end-to-end."""
    flags = flags or RunFlags()
    rid = run_id or make_run_id()
    started = time.monotonic()
    checkpoint_dir = repo_root / ".docspatch" / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    db_path = checkpoint_dir / "docs.sqlite"
    ledger = TokenLedger(checkpoint_dir, rid)

    ctx = GraphContext(
        generator=generator,
        sem=asyncio.Semaphore(concurrency_limit),
        repo_root=repo_root,
        tone=tone,
        cache=cache,
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

    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as saver:
        config: RunnableConfig = {"configurable": {"thread_id": rid}}
        existing = await load_state(saver, config)
        is_resume = bool(existing.get("generated") or existing.get("completed_batches"))

        # Remarks live on the generator, not in graph state — a resumed run
        # restores them from checkpoint metadata, overriding only on request.
        prior_remarks = (await load_metadata(saver, config)).get("remarks") if is_resume else None
        remarks = resolve_remarks(
            is_resume=is_resume, prior=prior_remarks, requested=flags.remarks, prompter=prompter
        )
        generator.remarks = remarks
        config = {"configurable": {"thread_id": rid}, "metadata": {"remarks": remarks}}

        plan_initial: PlanState = {"paths": paths, "repo_root": repo_root, "tone": tone, "flags": flags}
        if is_resume:
            plan_initial["confirmed"] = True
        plan_state = await build_plan_graph(ctx).ainvoke(plan_initial)

        if not plan_state.get("targets"):
            await saver.adelete_thread(rid)
            ledger.delete()
            return DocsResult(functions_documented=0, files_documented=0, batches=0)
        if not plan_state.get("confirmed"):
            ledger.delete()
            return DocsResult(functions_documented=0, files_documented=0, batches=0, confirmed=False)

        cache_hits = plan_state.get("cache_hits", 0)
        scanned = cache_hits + len(plan_state["targets"])

        # Only generate targets without a docstring already in the checkpoint —
        # a resumed run reuses what the prior run produced, no LLM re-call.
        done_keys = {(g.rel, g.qualname) for g in existing.get("generated", [])}
        missing = [t for t in plan_state["targets"] if (t.rel, t.qualname) not in done_keys]
        if is_resume:
            console.print(
                f"[dim]Resuming run {rid} · {len(done_keys)} done · {len(missing)} remaining[/dim]"
            )

        if missing:
            offset = max(existing.get("completed_batches", []), default=-1) + 1
            batches = batch_targets(ctx, missing, offset)
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
            ledger.delete()
            return DocsResult(functions_documented=0, files_documented=0, batches=batch_count)

        outcome = await drive_finalize(ctx, saver, review_handler, entries)
        await saver.adelete_thread(rid)
        usage = ledger.totals()
        elapsed = time.monotonic() - started
        if outcome.aborted:
            await saver.adelete_thread(f"review-{rid}")
            _render_docs_summary(
                outcome, usage=usage, provider=provider, tier=tier,
                elapsed=elapsed, cache_hits=cache_hits, scanned=scanned,
            )
            ledger.delete()
            return DocsResult(functions_documented=0, files_documented=0, batches=batch_count, aborted=True)

        _render_docs_summary(
            outcome, usage=usage, provider=provider, tier=tier,
            elapsed=elapsed, cache_hits=cache_hits, scanned=scanned,
        )
        ledger.delete()

    return DocsResult(
        functions_documented=outcome.fn_count,
        files_documented=len(outcome.committed),
        batches=batch_count,
        modules_documented=outcome.module_count,
        skipped_files=len(outcome.skipped),
        error=outcome.error,
    )
