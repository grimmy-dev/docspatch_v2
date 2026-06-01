"""Manage the batch summarization of code files via LLM interaction and cache persistence."""

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
    """Combine extracted AST metadata with LLM-generated summaries.

    Args:
        functions: The map of function names to metadata.
        llm_summaries: The map of function names to their LLM-generated descriptions.

    Returns:
        A list of updated FunctionMetadata objects.
    """
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
    """Write the merged summary for a file to the cache.

    Args:
        cache: The cache storage.
        miss: The file miss metadata.
        per_file: The summary output received from the LLM.
    """
    # Parse and gzip-write off the loop — this runs inside the concurrent batch
    # worker, so blocking here would stall other batches' in-flight LLM calls.
    functions = await asyncio.to_thread(extract_function_metadata, miss.source)
    merged = merge_function_summaries(functions, per_file.function_summaries)
    # Stat the file so the next run can fast-skip via size+mtime.
    try:
        st = (cache.root / miss.path).stat()
        size, mtime_ns = st.st_size, st.st_mtime_ns
    except OSError:
        size, mtime_ns = 0, 0
    summary = FileSummary(
        path=miss.path,
        summary=per_file.summary,
        functions=merged,
        interfaces=per_file.interfaces,
        relationships=per_file.relationships,
        # A change_note is only meaningful against a prior summary.
        change_note=per_file.change_note if miss.prior else None,
        compressed=miss.compressed,
        content_hash=miss.content_hash,
        size=size,
        mtime_ns=mtime_ns,
    )
    await asyncio.to_thread(cache.set, miss.path, summary)


async def summarize_batch(ctx: ScoutContext, batch: ScoutBatch) -> ScoutResult | None:
    """Execute the summarization for a specific batch.

    Args:
        ctx: The current scout context.
        batch: The batch of files to process.

    Returns:
        The result of the summary operation, or None if the batch should be retried.
    """
    misses = [ctx.misses[p] for p in batch.paths if p in ctx.misses]
    if not misses:
        return ScoutResult(scouted=0, skipped=0)
    try:
        return await _run_batch(ctx, misses)
    except TransientExhausted, asyncio.CancelledError, TimeoutError:
        return None
    except ParseFailed:
        return ScoutResult(scouted=0, skipped=0, unresolved=tuple(m.path for m in misses))


async def _invoke(ctx: ScoutContext, chain: TypedRunnable[BatchSummaryOutput], prompt: str) -> tuple[BatchSummaryOutput, TokenUsage]:
    """Perform a gated, timeout-bounded LLM call.

    Args:
        ctx: The scout context managing rate limits.
        chain: The executable LLM chain.
        prompt: The prompt string to process.

    Returns:
        A tuple containing the output object and token usage statistics.
    """
    async with ctx.gate:
        return await asyncio.wait_for(chain.ainvoke(prompt), timeout=ctx.call_timeout)


async def _run_batch(ctx: ScoutContext, misses: list[FileMiss]) -> ScoutResult:
    """Send a batch of files to the LLM and handle retries for unresolved files.

    Args:
        ctx: The scout context.
        misses: The list of file misses in the batch.

    Returns:
        The combined scouting result for the batch.
    """
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
    """Process the LLM response and update the cache for each recognized file.

    Args:
        ctx: The scout context.
        misses: The expected list of file misses.
        response: The structured output from the LLM.

    Returns:
        A tuple containing lists of successfully written files and remaining missing files.
    """
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
