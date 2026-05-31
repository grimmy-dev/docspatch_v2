"""Scout summarise graph: Send fan-out over token-sized batches, checkpointed.

Shares the docs pipeline's ``AsyncSqliteSaver`` (``.docspatch/checkpoints/docs.sqlite``)
under a ``scout-<run_id>`` thread namespace. ``run_scout`` re-issues unfinished
batches on the client returned by ``switch_handler`` after transient exhaustion.
"""

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
    """Wrap ``summarize_batch`` as a node. ``None`` leaves the batch unmarked."""

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
    """Summarise ``paths`` through the checkpointed scout graph, skipping cache hits.

    Misses are token-batched and fanned out as one LLM call each. On transient
    exhaustion the unfinished batches re-run on the client from ``switch_handler``;
    returning ``None`` aborts and keeps partial results.

    Args:
        paths: File paths to scout.
        ctx_store: Cache backend; hits are skipped.
        llm_client: Provider-normalised structured-output client.
        progress_cb: Optional per-file callback fired once a file lands in cache.
        batch_token_limit: Max compressed-source tokens per LLM call.
        concurrency_limit: Max parallel LLM batch calls.
        call_timeout: Seconds before a hung LLM call is cancelled and the batch re-issued.
        switch_handler: Optional callback invoked on transient exhaustion.
        run_id: Checkpoint thread id; generated when omitted.
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
