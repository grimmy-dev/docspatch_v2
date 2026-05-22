"""Scout summarise graph: Send fan-out over token-sized batches, checkpointed.

Shares the docs pipeline's ``AsyncSqliteSaver`` (``.docspatch/checkpoints/docs.sqlite``)
under a ``scout-<run_id>`` thread namespace. ``run_scout`` re-issues unfinished
batches on the client returned by ``switch_handler`` after transient exhaustion.
"""

import asyncio
from collections.abc import Callable

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from docspatch.cache import ScoutCache
from docspatch.checkpoints import make_run_id
from docspatch.constants import DEFAULT_BATCH_TOKEN_LIMIT, DEFAULT_CALL_TIMEOUT, DEFAULT_CONCURRENCY_LIMIT
from docspatch.llm import LLMClient
from docspatch.pipelines.scout.context import ProgressCb, ScoutContext, SwitchHandler, load_state
from docspatch.pipelines.scout.planner import partition_paths
from docspatch.pipelines.scout.state import ScoutBatch, ScoutResult, ScoutState
from docspatch.pipelines.scout.summarize import summarize_batch
from docspatch.source import estimate_tokens
from docspatch.utils.batcher import greedy_batches
from docspatch.utils.errors import TransientExhausted


def make_router() -> Callable[[ScoutState], list[Send] | str]:
    """Fan out to batches whose id is not yet in ``completed_batches``."""

    def route(state: ScoutState) -> list[Send] | str:
        completed = set(state.get("completed_batches", []))
        sends = [
            Send("summarize", {"batch": batch})
            for batch in state.get("batches", [])
            if batch.id not in completed
        ]
        return sends or END

    return route


def make_summarize(ctx: ScoutContext):  # noqa: ANN201 — returns a langgraph node callable
    """Wrap ``summarize_batch`` as a node. ``None`` leaves the batch unmarked."""

    async def summarize(payload: dict) -> ScoutState:
        batch: ScoutBatch = payload["batch"]
        result = await summarize_batch(ctx, batch)
        if result is None:
            return {}
        return {"completed_batches": [batch.id], "results": [result]}

    return summarize


def build_summarize_graph(ctx: ScoutContext, saver: AsyncSqliteSaver):  # noqa: ANN201
    """START → conditional Send fan-out (skipping done batches) → worker → END."""
    g: StateGraph = StateGraph(ScoutState)
    g.add_node("summarize", make_summarize(ctx))
    g.add_conditional_edges(START, make_router(), ["summarize", END])
    g.add_edge("summarize", END)
    return g.compile(checkpointer=saver)


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
    # partition_paths reads + libcst-compresses every file; offload so the
    # parsing never blocks the loop.
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
    db_path = ctx_store.root / ".docspatch" / "checkpoints" / "docs.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    config: RunnableConfig = {"configurable": {"thread_id": f"scout-{rid}"}}

    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as saver:
        graph = build_summarize_graph(ctx, saver)
        pending = batches
        while True:
            await graph.ainvoke({"batches": pending}, config=config)
            current = await load_state(saver, config)
            done = set(current.get("completed_batches", []))
            next_pending = [b for b in pending if b.id not in done]
            if not next_pending:
                break
            if switch_handler is None:
                raise TransientExhausted.after(0, RuntimeError("scout exhausted, no switch handler"))
            new_client = await switch_handler(ctx.client)
            if new_client is None:
                break
            ctx.client = new_client
            pending = next_pending

        results: list[ScoutResult] = list((await load_state(saver, config)).get("results", []))
        await saver.adelete_thread(f"scout-{rid}")

    return ScoutResult(
        scouted=sum(r.scouted for r in results),
        skipped=len(hits),
        input_tokens=sum(r.input_tokens for r in results),
        output_tokens=sum(r.output_tokens for r in results),
        unresolved=tuple(p for r in results for p in r.unresolved),
    )
