"""Scout pipeline runner. Token-batched, cache-skipping, concurrency-bounded.

Misses are token-batched with :func:`greedy_batches`, then each batch runs as
one LLM call returning a :class:`BatchSummaryOutput`. Concurrency is bounded
by an optional ``asyncio.Semaphore``. Cache writes off-load to a worker thread
so gzip + atomic write never blocks the event loop.

Missing-path safety: if the LLM response omits any requested path, those files
are retried once in isolated single-file batches before being marked unresolved.

Switch on exhaustion: when any batch raises :class:`TransientExhausted`, the
runner cancels the in-flight sibling tasks (discarding their results), invokes
``switch_handler`` to let the user pick a new provider/model, rebuilds the
chain on the returned client, and re-issues the failed + cancelled batches.
"""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager, nullcontext

from docspatch.context_store import ContextStore
from docspatch.llm import LLMClient
from docspatch.pipelines.scout.merge import store_summary
from docspatch.pipelines.scout.planner import partition_paths
from docspatch.pipelines.scout.prompts import build_batch_prompt
from docspatch.pipelines.scout.types import FileMiss, ScoutResult
from docspatch.types.llm import BatchSummaryOutput, StructuredChain
from docspatch.utils.batcher import Batch, greedy_batches
from docspatch.utils.errors import TransientExhausted
from docspatch.utils.sourcer import Sourcer

DEFAULT_BATCH_TOKEN_LIMIT = 6000

ProgressCb = Callable[[str], None]
Gate = AbstractAsyncContextManager[object]
SwitchHandler = Callable[[LLMClient], Awaitable[LLMClient | None]]
"""Async callback. Receives the exhausted client, returns a new one or None to abort."""


async def scout_files(
    paths: list[str],
    ctx_store: ContextStore,
    llm_client: LLMClient,
    progress_cb: ProgressCb | None = None,
    semaphore: asyncio.Semaphore | None = None,
    batch_token_limit: int = DEFAULT_BATCH_TOKEN_LIMIT,
    switch_handler: SwitchHandler | None = None,
) -> ScoutResult:
    """Summarise ``paths`` via LLM, skipping cache hits.

    Args:
        paths: File paths to scout.
        ctx_store: Cache backend; hits are skipped.
        llm_client: Provider-normalised structured-output client.
        progress_cb: Optional per-file callback fired after each file lands in cache.
        semaphore: Optional bound on parallel LLM batch calls.
        batch_token_limit: Max compressed-source tokens per LLM call.
        switch_handler: Optional async callback invoked when a batch exhausts
            retries. Returning a new ``LLMClient`` resumes the pending batches
            on that client; returning ``None`` aborts (partial results kept).
            When ``None`` is passed for this argument, :class:`TransientExhausted`
            propagates as before.
    """
    hits, misses = partition_paths(paths, ctx_store)
    for path in hits:
        if progress_cb:
            progress_cb(path)

    if not misses:
        return ScoutResult(scouted=0, skipped=len(hits), tokens_used=0)

    gate: Gate = semaphore if semaphore is not None else nullcontext()
    plan = greedy_batches(
        misses,
        size_fn=lambda m: Sourcer.estimate_tokens(m.compressed),
        limit=batch_token_limit,
    )

    completed = await _drive(list(plan.batches), llm_client, gate, ctx_store, progress_cb, switch_handler)

    return ScoutResult(
        scouted=sum(r.scouted for r in completed),
        skipped=len(hits),
        tokens_used=sum(r.tokens_used for r in completed),
        unresolved=tuple(p for r in completed for p in r.unresolved),
    )


async def _drive(
    pending: list[Batch[FileMiss]],
    client: LLMClient,
    gate: Gate,
    ctx_store: ContextStore,
    progress_cb: ProgressCb | None,
    switch_handler: SwitchHandler | None,
) -> list[ScoutResult]:
    """Run all ``pending`` batches; on transient exhaustion swap client and retry."""
    completed: list[ScoutResult] = []
    while pending:
        chain: StructuredChain[BatchSummaryOutput] = client.with_structured_output(BatchSummaryOutput)
        tasks = {asyncio.create_task(_run_batch(b, chain, gate, ctx_store, progress_cb)): b for b in pending}

        done, in_flight = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)

        next_pending: list[Batch[FileMiss]] = []
        exhausted = False
        for task in done:
            exc = task.exception()
            if exc is None:
                completed.append(task.result())
                continue
            if isinstance(exc, TransientExhausted):
                exhausted = True
                next_pending.append(tasks[task])
                continue
            for t in in_flight:
                t.cancel()
            await asyncio.gather(*in_flight, return_exceptions=True)
            raise exc

        if not exhausted:
            break

        for t in in_flight:
            t.cancel()
        await asyncio.gather(*in_flight, return_exceptions=True)
        next_pending.extend(tasks[t] for t in in_flight)

        if switch_handler is None:
            raise TransientExhausted.after(0, RuntimeError("scout exhausted, no switch handler"))

        new_client = await switch_handler(client)
        if new_client is None:
            return completed
        client = new_client
        pending = next_pending

    return completed


async def _run_batch(
    batch: Batch[FileMiss],
    chain: StructuredChain[BatchSummaryOutput],
    gate: Gate,
    ctx_store: ContextStore,
    progress_cb: ProgressCb | None,
) -> ScoutResult:
    """Send one batch as a single LLM call. Retry missing paths once in isolation."""
    prompt = build_batch_prompt(batch.items)
    async with gate:
        response: BatchSummaryOutput = await chain.ainvoke(prompt)

    written, missing = await _persist_response(batch.items, response, ctx_store, progress_cb)
    tokens_used = Sourcer.estimate_tokens(prompt)

    unresolved: list[str] = []
    for miss in missing:
        single_prompt = build_batch_prompt([miss])
        async with gate:
            retry_response: BatchSummaryOutput = await chain.ainvoke(single_prompt)
        tokens_used += Sourcer.estimate_tokens(single_prompt)
        per_file = retry_response.files.get(miss.path)
        if per_file is None:
            unresolved.append(miss.path)
            continue
        await store_summary(ctx_store, miss, per_file)
        written.append(miss.path)
        if progress_cb:
            progress_cb(miss.path)

    return ScoutResult(
        scouted=len(written),
        skipped=0,
        tokens_used=tokens_used,
        unresolved=tuple(unresolved),
    )


async def _persist_response(
    items: tuple[FileMiss, ...],
    response: BatchSummaryOutput,
    ctx_store: ContextStore,
    progress_cb: ProgressCb | None,
) -> tuple[list[str], list[FileMiss]]:
    """Write every recognised path; return (written paths, paths missing from response)."""
    written: list[str] = []
    missing: list[FileMiss] = []
    for miss in items:
        per_file = response.files.get(miss.path)
        if per_file is None:
            missing.append(miss)
            continue
        await store_summary(ctx_store, miss, per_file)
        written.append(miss.path)
        if progress_cb:
            progress_cb(miss.path)
    return written, missing
