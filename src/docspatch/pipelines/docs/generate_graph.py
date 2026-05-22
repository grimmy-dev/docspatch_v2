"""Generate graph: one LLM call per batch, fanned out with ``Send``.

Wired to an ``AsyncSqliteSaver`` so generated docs persist per super-step;
``run_generation`` re-issues unfinished batches after a provider switch.
"""

import asyncio
from collections.abc import Callable

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from docspatch.pipelines.docs.context import GraphContext, SwitchHandler, load_state
from docspatch.pipelines.docs.prompts import DocstringItem
from docspatch.pipelines.docs.state import BatchRef, GeneratedDoc, GenerateState, GenKey, TargetRef
from docspatch.ui.progress import BarHandle
from docspatch.utils.errors import ParseFailed, TransientExhausted


def build_generate_graph(ctx: GraphContext, saver: AsyncSqliteSaver):  # noqa: ANN201
    """START → conditional Send fan-out (skipping done) → worker → END. Checkpointed."""
    g: StateGraph = StateGraph(GenerateState)
    g.add_node("generate", make_generate(ctx))
    g.add_conditional_edges(START, make_router(), ["generate", END])
    g.add_edge("generate", END)
    return g.compile(checkpointer=saver)


def make_router() -> Callable[[GenerateState], list[Send] | str]:
    """Fan out to batches whose id is not in ``completed_batches``."""

    def route(state: GenerateState) -> list[Send] | str:
        completed = set(state.get("completed_batches", []))
        feedback = state.get("feedback", {})
        sends = [
            Send("generate", {"batch": batch, "feedback": feedback})
            for batch in state.get("batches", [])
            if batch.id not in completed
        ]
        return sends or END

    return route


async def generate_for_batch(
    ctx: GraphContext, batch: BatchRef, feedback: dict[str, list[str]]
) -> list[GeneratedDoc] | None:
    """Run one LLM call for ``batch``. ``None`` signals transient exhaustion/cancel."""
    items: list[DocstringItem] = []
    refs: list[TargetRef] = []
    for ref in batch.targets:
        t = ctx.full_targets.get((ref.rel, ref.qualname))
        if t is None:
            continue
        key = f"{ref.rel}::{ref.qualname}"
        items.append(
            DocstringItem(
                key=key,
                signature=t.signature,
                body=t.body,
                feedback=tuple(feedback.get(key, [])),
            )
        )
        refs.append(ref)

    if not items:
        return []

    try:
        async with ctx.sem:
            docs_map, usage = await asyncio.wait_for(
                ctx.generator.generate_batch(items, ctx.tone), timeout=ctx.call_timeout
            )
        ctx.ledger.append(batch.id, usage)
    except (TransientExhausted, asyncio.CancelledError, TimeoutError):
        # Exhaustion, Ctrl-C cancellation, or a hung call past call_timeout —
        # leave the batch unmarked so run_generation re-issues or switches.
        return None
    except ParseFailed as exc:
        # Schema validation failed twice — mark every item in the batch so the
        # review queue surfaces it. The batch is done; it is never re-issued.
        for ref in refs:
            if ctx.advance is not None:
                ctx.advance(f"{ref.rel}::{ref.qualname}")
        return [
            GeneratedDoc(
                rel=ref.rel,
                qualname=ref.qualname,
                docstring="",
                parse_failed=True,
                raw_output=exc.raw_output,
            )
            for ref in refs
        ]

    new_docs: list[GeneratedDoc] = []
    for ref in refs:
        doc = docs_map.get(f"{ref.rel}::{ref.qualname}")
        if doc is None:
            continue
        new_docs.append(GeneratedDoc(rel=ref.rel, qualname=ref.qualname, docstring=doc))
        if ctx.advance is not None:
            ctx.advance(f"{ref.rel}::{ref.qualname}")
    return new_docs


def make_generate(ctx: GraphContext):  # noqa: ANN201
    """One LLM call per batch. Semaphore caps cross-batch concurrency."""

    async def generate(payload: dict) -> GenerateState:
        batch: BatchRef = payload["batch"]
        docs = await generate_for_batch(ctx, batch, payload.get("feedback", {}))
        if docs is None:
            return {}
        return {"completed_batches": [batch.id], "generated": docs}

    return generate


async def run_generation(
    ctx: GraphContext,
    saver: AsyncSqliteSaver,
    config: RunnableConfig,
    pending: list[BatchRef],
    switch_handler: SwitchHandler | None,
    bar: BarHandle | None = None,
    *,
    initial_feedback: dict[str, list[str]] | None = None,
) -> None:
    """Run batches; on transient exhaustion swap generator and re-issue the unfinished set.

    Ctrl-C surfaces as ``asyncio.CancelledError`` inside the running node, where
    ``generate_for_batch`` catches it — the batch stays unmarked and the loop
    below treats it like any other unfinished batch.
    """
    wave = 0
    graph = build_generate_graph(ctx, saver)
    initial: GenerateState = {"batches": pending}
    if initial_feedback:
        initial["feedback"] = initial_feedback
    while True:
        await graph.ainvoke(initial, config=config)
        current = await load_state(saver, config)
        done_batch_ids = set(current.get("completed_batches", []))
        next_pending = [b for b in pending if b.id not in done_batch_ids]
        if not next_pending:
            return
        if switch_handler is None:
            raise TransientExhausted.after(0, RuntimeError("docs exhausted, no switch handler"))
        if bar is not None:
            bar.pause()
        try:
            new_gen = await switch_handler(ctx.generator)
        finally:
            if bar is not None:
                bar.resume()
        if new_gen is None:
            return
        ctx.generator = new_gen
        pending = next_pending
        wave += 1
        initial = {"batches": pending}
        if bar is not None:
            done_keys: set[GenKey] = {(d.rel, d.qualname) for d in current.get("generated", [])}
            remaining_fns = sum(
                1 for b in pending for ref in b.targets if (ref.rel, ref.qualname) not in done_keys
            )
            bar.set_status(f"Rerunning remaining · wave {wave} · {remaining_fns} fn(s)")
