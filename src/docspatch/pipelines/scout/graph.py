"""Construct the scouting graph for analyzing and summarizing codebase files.
This module handles batching, graph execution, and resource recovery."""

import asyncio

from langchain_core.runnables import RunnableConfig

from docspatch.cache import ScoutCache
from docspatch.checkpoints import make_run_id
from docspatch.checkpoints.saver import docs_db_path, open_checkpoint_saver
from docspatch.constants import DEFAULT_BATCH_TOKEN_LIMIT, DEFAULT_CALL_TIMEOUT, DEFAULT_CONCURRENCY_LIMIT
from docspatch.llm import LLMClient
from docspatch.pipelines.fanout import build_fanout_graph, run_fanout
from docspatch.pipelines.scout.context import ProgressCb, ScoutContext, SwitchHandler
from docspatch.pipelines.scout.planner import partition_paths
from docspatch.pipelines.scout.state import FileMiss, ScoutBatch, ScoutResult, ScoutState
from docspatch.pipelines.scout.summarize import summarize_batch
from docspatch.source import estimate_tokens
from docspatch.utils.batcher import greedy_batches


def make_summarize(ctx: ScoutContext):  # noqa: ANN201 — returns a langgraph node callable
    """Generate the graph node function for summarizing batches.

    Args:
        ctx: Scouting operational context.

    Returns:
        Node callable.
    """

    async def summarize(payload: dict) -> ScoutState:
        batch: ScoutBatch = payload["batch"]
        result = await summarize_batch(ctx, batch)
        if result is None:
            return {}
        return {"completed_batches": [batch.id], "results": [result]}

    return summarize


async def run_scout(
    paths: list[str],
    ctx_store: ScoutCache,
    llm_client: LLMClient,
    progress_cb: ProgressCb | None = None,
    batch_token_limit: int = DEFAULT_BATCH_TOKEN_LIMIT,
    concurrency_limit: int = DEFAULT_CONCURRENCY_LIMIT,
    call_timeout: float = DEFAULT_CALL_TIMEOUT,
    switch_handler: SwitchHandler | None = None,
    run_id: str | None = None,
    precomputed_misses: list[FileMiss] | None = None,
) -> ScoutResult:
    """Execute the scouting pipeline to summarize file contents.

    Args:
        paths: Files targeted for scanning.
        ctx_store: Persistent cache for skipping known files.
        llm_client: Client for LLM summarization.

    Returns:
        Aggregate scout result summary.
    """
    # Reuse planner output when given; otherwise read+compress here (offloaded).
    if precomputed_misses is not None:
        hits: list[str] = []
        misses = list(precomputed_misses)
    else:
        hits, misses = await asyncio.to_thread(partition_paths, paths, ctx_store)
    for path in hits:
        if progress_cb:
            progress_cb(path)

    if not misses:
        return ScoutResult(scouted=0, skipped=len(hits))

    plan = greedy_batches(misses, size_fn=lambda m: estimate_tokens(m.compressed), limit=batch_token_limit)
    batches = [ScoutBatch(id=i, paths=[m.path for m in b.items]) for i, b in enumerate(plan.batches)]

    ctx = ScoutContext(
        client=llm_client,
        misses={m.path: m for m in misses},
        cache=ctx_store,
        gate=asyncio.Semaphore(concurrency_limit),
        progress_cb=progress_cb,
        call_timeout=call_timeout,
    )

    rid = run_id or make_run_id()
    config: RunnableConfig = {"configurable": {"thread_id": f"scout-{rid}"}}

    async def switch() -> bool:
        assert switch_handler is not None  # only wired in when a handler exists
        new_client = await switch_handler(ctx.client)
        if new_client is None:
            return False
        ctx.client = new_client
        return True

    async with open_checkpoint_saver(docs_db_path(ctx_store.root)) as saver:
        graph = build_fanout_graph(ScoutState, "summarize", make_summarize(ctx), lambda _s, b: {"batch": b}, saver)
        final = await run_fanout(
            graph,
            saver,
            config,
            initial={"batches": batches},
            pending=batches,
            switch=switch if switch_handler is not None else None,
            label="scout",
        )
        results: list[ScoutResult] = list(final.get("results", []))
        await saver.adelete_thread(f"scout-{rid}")

    return ScoutResult(
        scouted=sum(r.scouted for r in results),
        skipped=len(hits),
        input_tokens=sum(r.input_tokens for r in results),
        output_tokens=sum(r.output_tokens for r in results),
        unresolved=tuple(p for r in results for p in r.unresolved),
    )
