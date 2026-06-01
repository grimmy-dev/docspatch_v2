"""Async-correctness tests: the loop is never serialized by CPU-bound work."""

import asyncio
import re
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import docspatch.pipelines.scout.summarize as summarize_mod
from docspatch.cache import ScoutCache
from docspatch.llm import TokenUsage
from docspatch.pipelines.scout.graph import run_scout
from docspatch.schemas import BatchSummaryOutput, FileSummaryOutput

SAMPLE_SOURCE = "def foo():\n    return 1\n"
USAGE = TokenUsage(input_tokens=80, output_tokens=20)
PATH_HEADER = re.compile(r"^===== PATH: (.+?) =====$", re.MULTILINE)


def sleeping_client(delay: float) -> MagicMock:
    """Mock scout client whose every LLM call sleeps ``delay`` seconds."""
    client = MagicMock()
    chain = MagicMock()

    async def fake_ainvoke(prompt: str) -> tuple[BatchSummaryOutput, TokenUsage]:
        await asyncio.sleep(delay)
        paths = PATH_HEADER.findall(prompt)
        return BatchSummaryOutput(files={p: FileSummaryOutput(summary="s") for p in paths}), USAGE

    chain.ainvoke = AsyncMock(side_effect=fake_ainvoke)
    client.with_structured_output.return_value = chain
    return client


def write_files(tmp_path: Path, count: int) -> list[str]:
    paths = []
    for i in range(count):
        p = tmp_path / f"f{i}.py"
        p.write_text(SAMPLE_SOURCE)
        paths.append(str(p))
    return paths


def test_concurrent_batches_finish_in_one_batch_walltime(tmp_path: Path) -> None:
    """5 batches with a 0.2s mock call finish in ~one call, not 5 in series."""
    paths = write_files(tmp_path, 5)
    delay = 0.2

    start = time.monotonic()
    result = asyncio.run(
        run_scout(
            paths,
            ScoutCache(repo_root=tmp_path),
            sleeping_client(delay),
            batch_token_limit=1,  # one file per batch → 5 batches
            concurrency_limit=5,
        )
    )
    elapsed = time.monotonic() - start

    assert result.scouted == 5
    # Concurrent: ≈ one delay. Serialized would be 5×. Loose bound for CI noise.
    assert elapsed < delay * 3


def test_heavy_parse_in_worker_does_not_stall_other_batches(tmp_path: Path, monkeypatch) -> None:
    """A blocking parse inside one batch's worker must not freeze the others.

    ``store_summary`` offloads ``extract_function_metadata``; if it ran on the
    loop, the three batches' parses would serialize to ~3× the parse time.
    """
    paths = write_files(tmp_path, 3)
    parse_cost = 0.2
    real_extract = summarize_mod.extract_function_metadata

    def slow_extract(source: str):
        time.sleep(parse_cost)  # blocking CPU stand-in
        return real_extract(source)

    monkeypatch.setattr(summarize_mod, "extract_function_metadata", slow_extract)

    start = time.monotonic()
    result = asyncio.run(
        run_scout(
            paths,
            ScoutCache(repo_root=tmp_path),
            sleeping_client(0.0),
            batch_token_limit=1,
            concurrency_limit=3,
        )
    )
    elapsed = time.monotonic() - start

    assert result.scouted == 3
    # Offloaded → parses run in parallel threads ≈ one parse_cost.
    assert elapsed < parse_cost * 2.5
