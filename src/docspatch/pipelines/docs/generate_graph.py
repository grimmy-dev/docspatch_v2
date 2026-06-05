"""Defines the parallel generation graph that batches, requests, and processes docstrings from an LLM client."""

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


async def generate_for_batch(ctx: GraphContext, batch: BatchRef, feedback: dict[str, list[str]]) -> list[GeneratedDoc] | None:
    """Query the LLM generator for a batch of docstrings, updating the token usage ledger and handling failures.

    Args:
        ctx: The documentation pipeline context.
        batch: The target references to document in a single call.
        feedback: Prior correction requests mapped by target keys.

    Returns:
        The list of generated docstrings, or None if a transient failure occurs.
    """
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
            docs_map, usage = await asyncio.wait_for(ctx.generator.generate_batch(items, ctx.tone), timeout=ctx.call_timeout)
        ctx.ledger.append(batch.id, usage)
    except TransientExhausted, asyncio.CancelledError, TimeoutError:
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
        key = f"{ref.rel}::{ref.qualname}"
        doc = docs_map.get(key)
        if doc and doc.strip():
            new_docs.append(GeneratedDoc(rel=ref.rel, qualname=ref.qualname, docstring=doc))
        else:
            # Model omitted this key even after retries — surface it for review
            # instead of dropping it, so --update never silently skips a function.
            new_docs.append(GeneratedDoc(rel=ref.rel, qualname=ref.qualname, docstring="", parse_failed=True))
        if ctx.advance is not None:
            ctx.advance(key)
    return new_docs


def make_generate(ctx: GraphContext):  # noqa: ANN201
    """Construct an asynchronous generation node that processes a batch of target docstrings with concurrency limits.

    Args:
        ctx: The documentation pipeline context.

    Returns:
        The graph node function that executes the batch call.
    """

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
    """Execute parallelized batch generation and coordinate fallback model switching when transient errors occur.

    Args:
        ctx: The documentation pipeline context.
        saver: The persistent storage provider for checkpointing.
        config: LangGraph execution configuration with thread identifier.
        pending: List of target batches waiting for generation.
        switch_handler: The callback to swap LLM clients on error.
        bar: Optional CLI progress bar to update.
        initial_feedback: Starting user feedback remarks to incorporate.
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
        remaining_fns = sum(1 for b in remaining for ref in b.targets if (ref.rel, ref.qualname) not in done_keys)
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
