"""Merge LLM per-function summaries onto AST-extracted FunctionMetadata."""

import asyncio

from docspatch.context_store import ContextStore
from docspatch.pipelines.scout.types import FileMiss
from docspatch.types.llm import FileSummaryOutput
from docspatch.types.source import FileSummary, FunctionMetadata
from docspatch.utils.sourcer import Sourcer


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


async def store_summary(ctx_store: ContextStore, miss: FileMiss, per_file: FileSummaryOutput) -> None:
    """Persist the merged summary for ``miss`` to the cache (off the event loop)."""
    functions = Sourcer.extract_functions(miss.source)
    merged = merge_function_summaries(functions, per_file.function_summaries)
    summary = FileSummary(
        path=miss.path,
        summary=per_file.summary,
        functions=merged,
        content_hash=miss.content_hash,
    )
    await asyncio.to_thread(ctx_store.set_summary, miss.path, summary)
