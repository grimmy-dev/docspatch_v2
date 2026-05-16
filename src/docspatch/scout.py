"""Scout deep module — cache-aware parallel file summarisation via LLM."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from docspatch.context_store import ContextStore
from docspatch.llm_client import LLMClient
from docspatch.sourcer import Sourcer
from docspatch.types.llm import FileSummaryOutput, StructuredChain
from docspatch.types.source import FileSummary


@dataclass
class ScoutResult:
    scouted: int
    skipped: int
    tokens_used: int


class FileMiss(NamedTuple):
    path: str
    source: str
    content_hash: str


async def scout_files(
    paths: list[str],
    ctx_store: ContextStore,
    llm_client: LLMClient,
    progress_cb: Callable[[str], None] | None = None,
) -> ScoutResult:
    """Summarise files via LLM, skipping cache hits. Returns scouted/skipped counts and token estimate."""
    hits: list[str] = []
    misses: list[FileMiss] = []

    for path in paths:
        try:
            source = Path(path).read_text(encoding="utf-8")
        except OSError:
            continue
        content_hash = Sourcer.hash(source)
        cached = ctx_store.get_summary(path)
        if cached and cached.content_hash == content_hash:
            hits.append(path)
        else:
            misses.append(FileMiss(path, source, content_hash))

    for path in hits:
        if progress_cb:
            progress_cb(path)

    if not misses:
        return ScoutResult(scouted=0, skipped=len(hits), tokens_used=0)

    chain: StructuredChain[FileSummaryOutput] = llm_client.with_structured_output(FileSummaryOutput)

    async def process(miss: FileMiss) -> int:
        compressed = Sourcer.compress(miss.source)
        prompt = f"Summarise this Python module. Return summary and key_symbols.\n\n{compressed}"
        result: FileSummaryOutput = await chain.ainvoke(prompt)
        ctx_store.set_summary(
            miss.path,
            FileSummary(
                path=miss.path,
                summary=result.summary,
                functions=list(Sourcer.extract_functions(miss.source).values()),
                content_hash=miss.content_hash,
            ),
        )
        if progress_cb:
            progress_cb(miss.path)
        return Sourcer.estimate_tokens(prompt)

    token_counts = await asyncio.gather(*(process(m) for m in misses))

    return ScoutResult(scouted=len(misses), skipped=len(hits), tokens_used=sum(token_counts))
