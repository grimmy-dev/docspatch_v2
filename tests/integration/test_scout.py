"""Scout + RunContext behavior tests — real filesystem, mocked LLM, no network."""

import asyncio
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from docspatch.cache import ScoutCache
from docspatch.llm import TokenUsage
from docspatch.pipelines.scout.graph import run_scout
from docspatch.source import file_hash
from docspatch.types.config import DocspatchConfig
from docspatch.types.llm import BatchSummaryOutput, FileSummaryOutput
from docspatch.types.source import FileSummary
from docspatch.utils.run_context import RunContext

SAMPLE_SOURCE = "def foo():\n    return 1\n"

SCOUT_USAGE = TokenUsage(input_tokens=80, output_tokens=20)
"""Canned per-call token usage every mocked scout chain reports."""

PATH_HEADER = re.compile(r"^===== PATH: (.+?) =====$", re.MULTILINE)


def make_llm_client(summary: str = "does stuff") -> MagicMock:
    """Mock chain that echoes back a summary for every path it finds in the prompt."""
    client = MagicMock()
    chain = MagicMock()

    async def fake_ainvoke(prompt: str) -> tuple[BatchSummaryOutput, TokenUsage]:
        paths = PATH_HEADER.findall(prompt)
        files = {
            p: FileSummaryOutput(summary=summary, function_summaries={"foo": "returns 1"})
            for p in paths
        }
        return BatchSummaryOutput(files=files), SCOUT_USAGE

    chain.ainvoke = AsyncMock(side_effect=fake_ainvoke)
    client.with_structured_output.return_value = chain
    return client


def make_store(tmp_path: Path) -> ScoutCache:
    return ScoutCache(repo_root=tmp_path)


# --- cache hit / miss ---


def test_scout_skips_cache_hits(tmp_path):
    store = make_store(tmp_path)
    src = tmp_path / "a.py"
    src.write_text(SAMPLE_SOURCE)
    path = str(src)
    store.set(path, FileSummary(path=path, summary="old", content_hash=file_hash(SAMPLE_SOURCE)))

    client = make_llm_client()
    result = asyncio.run(run_scout([path], store, client))

    assert result.skipped == 1
    assert result.scouted == 0
    client.with_structured_output.assert_not_called()


def test_scout_processes_misses(tmp_path):
    store = make_store(tmp_path)
    src = tmp_path / "b.py"
    src.write_text(SAMPLE_SOURCE)

    result = asyncio.run(run_scout([str(src)], store, make_llm_client()))

    assert result.scouted == 1
    assert result.skipped == 0


def test_scout_stale_hash_treated_as_miss(tmp_path):
    store = make_store(tmp_path)
    src = tmp_path / "c.py"
    src.write_text(SAMPLE_SOURCE)
    path = str(src)
    store.set(path, FileSummary(path=path, summary="old", content_hash="stale-hash"))

    result = asyncio.run(run_scout([path], store, make_llm_client()))

    assert result.scouted == 1
    assert result.skipped == 0


# --- storage ---


def test_scout_stores_result_in_context_store(tmp_path):
    store = make_store(tmp_path)
    src = tmp_path / "d.py"
    src.write_text(SAMPLE_SOURCE)
    path = str(src)

    asyncio.run(run_scout([path], store, make_llm_client("summary here")))

    saved = store.get(path)
    assert saved is not None
    assert saved.summary == "summary here"
    assert saved.content_hash == file_hash(SAMPLE_SOURCE)


def test_scout_attaches_llm_summary_to_functions(tmp_path):
    store = make_store(tmp_path)
    src = tmp_path / "h.py"
    src.write_text(SAMPLE_SOURCE)
    path = str(src)

    asyncio.run(run_scout([path], store, make_llm_client()))

    saved = store.get(path)
    assert saved is not None
    assert saved.functions
    fn = saved.functions[0]
    assert fn.name == "foo"
    assert fn.llm_summary == "returns 1"


# --- ScoutResult fields ---


def test_scout_result_tokens_used_nonzero(tmp_path):
    store = make_store(tmp_path)
    src = tmp_path / "e.py"
    src.write_text(SAMPLE_SOURCE)

    result = asyncio.run(run_scout([str(src)], store, make_llm_client()))

    assert result.input_tokens > 0


def test_scout_result_tokens_zero_on_all_hits(tmp_path):
    store = make_store(tmp_path)
    src = tmp_path / "f.py"
    src.write_text(SAMPLE_SOURCE)
    path = str(src)
    store.set(path, FileSummary(path=path, summary="x", content_hash=file_hash(SAMPLE_SOURCE)))

    result = asyncio.run(run_scout([path], store, make_llm_client()))

    assert result.input_tokens == 0


# --- progress callback ---


def test_scout_progress_cb_called_for_every_file(tmp_path):
    store = make_store(tmp_path)
    hit = tmp_path / "hit.py"
    miss = tmp_path / "miss.py"
    hit.write_text(SAMPLE_SOURCE)
    miss.write_text(SAMPLE_SOURCE)
    hit_path = str(hit)
    store.set(hit_path, FileSummary(path=hit_path, summary="x", content_hash=file_hash(SAMPLE_SOURCE)))

    calls: list[str] = []
    asyncio.run(run_scout([hit_path, str(miss)], store, make_llm_client(), progress_cb=calls.append))

    assert len(calls) == 2


def test_scout_no_progress_cb_does_not_raise(tmp_path):
    store = make_store(tmp_path)
    src = tmp_path / "g.py"
    src.write_text(SAMPLE_SOURCE)

    asyncio.run(run_scout([str(src)], store, make_llm_client()))  # no progress_cb


# --- parallel gather ---


def test_scout_packs_small_files_into_one_batch(tmp_path):
    store = make_store(tmp_path)
    paths = []
    for i in range(3):
        p = tmp_path / f"p{i}.py"
        p.write_text(SAMPLE_SOURCE)
        paths.append(str(p))

    client = make_llm_client()
    result = asyncio.run(run_scout(paths, store, client, batch_token_limit=10_000))

    assert result.scouted == 3
    # All three small files fit in one batch → single LLM call.
    assert client.with_structured_output.return_value.ainvoke.await_count == 1


def test_scout_splits_when_batch_token_limit_small(tmp_path):
    store = make_store(tmp_path)
    paths = []
    for i in range(3):
        p = tmp_path / f"p{i}.py"
        p.write_text(SAMPLE_SOURCE)
        paths.append(str(p))

    client = make_llm_client()
    # Tiny limit → each file forced into its own batch (oversized path).
    result = asyncio.run(run_scout(paths, store, client, batch_token_limit=1))

    assert result.scouted == 3
    assert client.with_structured_output.return_value.ainvoke.await_count == 3


def test_scout_semaphore_bounds_concurrency(tmp_path):
    store = make_store(tmp_path)
    paths = []
    for i in range(4):
        p = tmp_path / f"q{i}.py"
        p.write_text(SAMPLE_SOURCE)
        paths.append(str(p))

    client = MagicMock()
    chain = MagicMock()
    inflight = 0
    peak = 0

    async def gated_ainvoke(prompt: str) -> tuple[BatchSummaryOutput, TokenUsage]:
        nonlocal inflight, peak
        inflight += 1
        peak = max(peak, inflight)
        await asyncio.sleep(0.01)
        inflight -= 1
        paths_in = PATH_HEADER.findall(prompt)
        return BatchSummaryOutput(files={p: FileSummaryOutput(summary="s") for p in paths_in}), SCOUT_USAGE

    chain.ainvoke = AsyncMock(side_effect=gated_ainvoke)
    client.with_structured_output.return_value = chain

    asyncio.run(run_scout(paths, store, client, concurrency_limit=2, batch_token_limit=1))
    assert peak <= 2


def test_scout_retries_missing_paths_in_isolation(tmp_path):
    store = make_store(tmp_path)
    paths = []
    for i in range(2):
        p = tmp_path / f"r{i}.py"
        p.write_text(SAMPLE_SOURCE)
        paths.append(str(p))

    client = MagicMock()
    chain = MagicMock()
    calls = {"n": 0}

    async def flaky(prompt: str) -> tuple[BatchSummaryOutput, TokenUsage]:
        calls["n"] += 1
        paths_in = PATH_HEADER.findall(prompt)
        # First call (the batch) omits the second path.
        if calls["n"] == 1 and len(paths_in) == 2:
            return BatchSummaryOutput(files={paths_in[0]: FileSummaryOutput(summary="ok")}), SCOUT_USAGE
        return BatchSummaryOutput(files={p: FileSummaryOutput(summary="ok-retry") for p in paths_in}), SCOUT_USAGE

    chain.ainvoke = AsyncMock(side_effect=flaky)
    client.with_structured_output.return_value = chain

    result = asyncio.run(run_scout(paths, store, client, batch_token_limit=10_000))
    assert result.scouted == 2
    assert result.unresolved == ()


# --- switch on exhaustion ---


def test_scout_invokes_switch_handler_on_transient_exhausted(tmp_path):
    """When a batch raises TransientExhausted, the runner asks for a new client and resumes."""
    from docspatch.utils.errors import TransientExhausted

    store = make_store(tmp_path)
    paths = []
    for i in range(2):
        src = tmp_path / f"s{i}.py"
        src.write_text(SAMPLE_SOURCE)
        paths.append(str(src))

    bad_chain = MagicMock()
    bad_chain.ainvoke = AsyncMock(side_effect=TransientExhausted.after(3, RuntimeError("rate_limit")))
    bad_client = MagicMock()
    bad_client.with_structured_output.return_value = bad_chain
    bad_client.provider = "anthropic"
    bad_client.generator_model = "claude-haiku"

    good_client = make_llm_client("after switch")

    async def handler(current):
        return good_client

    result = asyncio.run(run_scout(paths, store, bad_client, switch_handler=handler, batch_token_limit=10_000))
    assert result.scouted == 2
    # Good client's chain was used after the swap.
    assert good_client.with_structured_output.return_value.ainvoke.await_count >= 1


def test_scout_switch_handler_abort_returns_partial(tmp_path):
    """When the switch handler returns None, the runner stops with partial results."""
    from docspatch.utils.errors import TransientExhausted

    store = make_store(tmp_path)
    src = tmp_path / "only.py"
    src.write_text(SAMPLE_SOURCE)

    bad_chain = MagicMock()
    bad_chain.ainvoke = AsyncMock(side_effect=TransientExhausted.after(3, RuntimeError("429")))
    bad_client = MagicMock()
    bad_client.with_structured_output.return_value = bad_chain
    bad_client.provider = "anthropic"
    bad_client.generator_model = "claude-haiku"

    async def handler(current):
        return None

    result = asyncio.run(run_scout([str(src)], store, bad_client, switch_handler=handler, batch_token_limit=10_000))
    assert result.scouted == 0


def test_scout_parse_failure_marks_files_unresolved(tmp_path):
    """A batch whose structured output fails schema validation reports its files unresolved."""
    from docspatch.utils.errors import ParseFailed

    store = make_store(tmp_path)
    src = tmp_path / "pf.py"
    src.write_text(SAMPLE_SOURCE)

    bad_chain = MagicMock()
    bad_chain.ainvoke = AsyncMock(side_effect=ParseFailed.after_retry(ValueError("bad schema")))
    client = MagicMock()
    client.with_structured_output.return_value = bad_chain

    result = asyncio.run(run_scout([str(src)], store, client, batch_token_limit=10_000))
    assert result.scouted == 0
    assert result.unresolved == (str(src),)


def test_scout_hung_call_cancelled_by_timeout(tmp_path):
    """A batch whose LLM call hangs past call_timeout is re-issued on the switched client."""
    store = make_store(tmp_path)
    src = tmp_path / "hang.py"
    src.write_text(SAMPLE_SOURCE)

    hang_chain = MagicMock()

    async def never_returns(prompt: str) -> tuple[BatchSummaryOutput, TokenUsage]:
        await asyncio.sleep(60)
        raise AssertionError("should have been cancelled")

    hang_chain.ainvoke = AsyncMock(side_effect=never_returns)
    hang_client = MagicMock()
    hang_client.with_structured_output.return_value = hang_chain

    good_client = make_llm_client("after timeout")

    async def handler(current):
        return good_client

    result = asyncio.run(
        run_scout(
            [str(src)],
            store,
            hang_client,
            switch_handler=handler,
            batch_token_limit=10_000,
            call_timeout=0.05,
        )
    )
    assert result.scouted == 1


# --- RunContext ---


def test_run_context_progress_calls_callback(tmp_path):
    calls: list[str] = []
    ctx = RunContext(
        llm_client=MagicMock(),
        ctx_store=make_store(tmp_path),
        config=DocspatchConfig(),
        progress_cb=calls.append,
    )
    ctx.progress("step 1")
    assert calls == ["step 1"]


def test_run_context_default_noop_progress_does_not_raise(tmp_path):
    ctx = RunContext(
        llm_client=MagicMock(),
        ctx_store=make_store(tmp_path),
        config=DocspatchConfig(),
    )
    ctx.progress("no-op")


def test_run_context_scout_returns_scouted_count(tmp_path):
    src = tmp_path / "mod.py"
    src.write_text(SAMPLE_SOURCE)

    ctx = RunContext(
        llm_client=make_llm_client(),
        ctx_store=make_store(tmp_path),
        config=DocspatchConfig(),
    )
    result = asyncio.run(ctx.scout([str(src)]))

    assert result.scouted == 1
    assert result.skipped == 0
