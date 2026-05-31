"""Generate graph: one LLM call per batch, fanned out with ``Send``.

Wired to an ``AsyncSqliteSaver`` so generated docs persist per super-step;
``run_generation`` re-issues unfinished batches after a provider switch.
"""

import asyncio
from collections.abc import Sequence
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from docspatch.pipelines.docs.context import GraphContext, SwitchHandler
from docspatch.pipelines.docs.prompts import DocstringItem
from docspatch.pipelines.docs.state import BatchRef, GeneratedDoc, GenerateState, GenKey, TargetRef
from docspatch.pipelines.fanout import build_fanout_graph, run_fanout
from docspatch.ui.progress import BarHandle
from docspatch.utils.errors import ParseFailed, TransientExhausted


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
    ``generate_for_batch`` catches it — the batch stays unmarked and ``run_fanout``
    treats it like any other unfinished batch.
    """
    def payload_fn(state: dict[str, Any], b: BatchRef) -> dict[str, Any]:
        return {"batch": b, "feedback": state.get("feedback", {})}

    graph = build_fanout_graph(GenerateState, "generate", make_generate(ctx), payload_fn, saver)

    async def switch() -> bool:
        assert switch_handler is not None  # only wired in when a handler exists
        if bar is not None:
            bar.pause()
        try:
            new_gen = await switch_handler(ctx.generator)
        finally:
            if bar is not None:
                bar.resume()
        if new_gen is None:
            return False
        ctx.generator = new_gen
        return True

    def on_wave(wave: int, current: dict[str, Any], remaining: Sequence[BatchRef]) -> None:
        if bar is None:
            return
        done_keys: set[GenKey] = {(d.rel, d.qualname) for d in current.get("generated", [])}
        remaining_fns = sum(
            1 for b in remaining for ref in b.targets if (ref.rel, ref.qualname) not in done_keys
        )
        bar.set_status(f"Rerunning remaining · wave {wave} · {remaining_fns} fn(s)")

    initial: GenerateState = {"batches": pending}
    if initial_feedback:
        initial["feedback"] = initial_feedback

    await run_fanout(
        graph,
        saver,
        config,
        initial=dict(initial),
        pending=pending,
        switch=switch if switch_handler is not None else None,
        label="docs",
        on_wave=on_wave if bar is not None else None,
    )
