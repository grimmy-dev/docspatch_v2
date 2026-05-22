"""Per-batch scout summarisation — the LangGraph worker node's payload.

One worker invocation summarises one token-sized batch in a single LLM call.
Files the model omits from its response are retried once in isolated
single-file calls before being reported unresolved. Cache writes off-load to a
worker thread so gzip + atomic write never block the event loop.
"""

import asyncio

from docspatch.cache import ScoutCache
from docspatch.llm import TokenUsage, TypedRunnable
from docspatch.pipelines.scout.context import ScoutContext
from docspatch.pipelines.scout.prompts import build_batch_prompt
from docspatch.pipelines.scout.state import FileMiss, ScoutBatch, ScoutResult
from docspatch.schemas import BatchSummaryOutput, FileSummary, FileSummaryOutput, FunctionMetadata
from docspatch.source import extract_function_metadata
from docspatch.utils.errors import ParseFailed, TransientExhausted


def merge_function_summaries(
    functions: dict[str, FunctionMetadata],
    llm_summaries: dict[str, str],
) -> list[FunctionMetadata]:
    """Attach LLM one-liners onto AST-extracted FunctionMetadata."""
    return [
        FunctionMetadata(
            name=fn.name,
            signature=fn.signature,
            docstring=fn.docstring,
            llm_summary=llm_summaries.get(fn.name),
            line_start=fn.line_start,
            line_end=fn.line_end,
        )
        for fn in functions.values()
    ]


async def store_summary(cache: ScoutCache, miss: FileMiss, per_file: FileSummaryOutput) -> None:
    """Persist the merged summary for ``miss`` to the cache (off the event loop)."""
    functions = extract_function_metadata(miss.source)
    merged = merge_function_summaries(functions, per_file.function_summaries)
    summary = FileSummary(
        path=miss.path,
        summary=per_file.summary,
        functions=merged,
        content_hash=miss.content_hash,
    )
    await asyncio.to_thread(cache.set, miss.path, summary)


async def summarize_batch(ctx: ScoutContext, batch: ScoutBatch) -> ScoutResult | None:
    """Summarise one batch via a single LLM call.

    Returns ``None`` on transient exhaustion, cancellation, or timeout so the
    graph leaves the batch unmarked and ``run_scout`` can re-issue it. A schema
    parse failure is terminal: its files are reported unresolved, not re-issued.
    """
    misses = [ctx.misses[p] for p in batch.paths if p in ctx.misses]
    if not misses:
        return ScoutResult(scouted=0, skipped=0)
    try:
        return await _run_batch(ctx, misses)
    except (TransientExhausted, asyncio.CancelledError, TimeoutError):
        return None
    except ParseFailed:
        return ScoutResult(scouted=0, skipped=0, unresolved=tuple(m.path for m in misses))


async def _invoke(
    ctx: ScoutContext, chain: TypedRunnable[BatchSummaryOutput], prompt: str
) -> tuple[BatchSummaryOutput, TokenUsage]:
    """One gated, timeout-bounded LLM call. A hung call past ``call_timeout`` raises."""
    async with ctx.gate:
        return await asyncio.wait_for(chain.ainvoke(prompt), timeout=ctx.call_timeout)


async def _run_batch(ctx: ScoutContext, misses: list[FileMiss]) -> ScoutResult:
    """Send one batch as a single LLM call; retry omitted paths once in isolation."""
    chain = ctx.client.with_structured_output(BatchSummaryOutput)
    response, usage = await _invoke(ctx, chain, build_batch_prompt(misses))

    written, missing = await _persist(ctx, misses, response)

    unresolved: list[str] = []
    for miss in missing:
        retry, retry_usage = await _invoke(ctx, chain, build_batch_prompt([miss]))
        usage += retry_usage
        per_file = retry.files.get(miss.path)
        if per_file is None:
            unresolved.append(miss.path)
            continue
        await store_summary(ctx.cache, miss, per_file)
        written.append(miss.path)
        if ctx.progress_cb:
            ctx.progress_cb(miss.path)

    return ScoutResult(
        scouted=len(written),
        skipped=0,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        unresolved=tuple(unresolved),
    )


async def _persist(
    ctx: ScoutContext,
    misses: list[FileMiss],
    response: BatchSummaryOutput,
) -> tuple[list[str], list[FileMiss]]:
    """Write every recognised path; return (written paths, paths missing from response)."""
    written: list[str] = []
    missing: list[FileMiss] = []
    for miss in misses:
        per_file = response.files.get(miss.path)
        if per_file is None:
            missing.append(miss)
            continue
        await store_summary(ctx.cache, miss, per_file)
        written.append(miss.path)
        if ctx.progress_cb:
            ctx.progress_cb(miss.path)
    return written, missing
