"""Scout + RunContext behavior tests — real filesystem, mocked LLM, no network."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from docspatch.context_store import ContextStore
from docspatch.run_context import RunContext
from docspatch.scout import scout_files
from docspatch.sourcer import Sourcer
from docspatch.types.config import DocspatchConfig
from docspatch.types.llm import FileSummaryOutput
from docspatch.types.source import FileSummary

SAMPLE_SOURCE = "def foo():\n    return 1\n"


def make_llm_client(summary: str = "does stuff") -> MagicMock:
    client = MagicMock()
    chain = MagicMock()
    chain.ainvoke = AsyncMock(return_value=FileSummaryOutput(summary=summary, key_symbols=["foo"]))
    client.with_structured_output.return_value = chain
    return client


def make_store(tmp_path: Path) -> ContextStore:
    return ContextStore(repo_root=tmp_path)


# --- cache hit / miss ---


def test_scout_skips_cache_hits(tmp_path):
    store = make_store(tmp_path)
    src = tmp_path / "a.py"
    src.write_text(SAMPLE_SOURCE)
    path = str(src)
    store.set_summary(path, FileSummary(path=path, summary="old", content_hash=Sourcer.hash(SAMPLE_SOURCE)))

    client = make_llm_client()
    result = asyncio.run(scout_files([path], store, client))

    assert result.skipped == 1
    assert result.scouted == 0
    client.with_structured_output.assert_not_called()


def test_scout_processes_misses(tmp_path):
    store = make_store(tmp_path)
    src = tmp_path / "b.py"
    src.write_text(SAMPLE_SOURCE)

    result = asyncio.run(scout_files([str(src)], store, make_llm_client()))

    assert result.scouted == 1
    assert result.skipped == 0


def test_scout_stale_hash_treated_as_miss(tmp_path):
    store = make_store(tmp_path)
    src = tmp_path / "c.py"
    src.write_text(SAMPLE_SOURCE)
    path = str(src)
    store.set_summary(path, FileSummary(path=path, summary="old", content_hash="stale-hash"))

    result = asyncio.run(scout_files([path], store, make_llm_client()))

    assert result.scouted == 1
    assert result.skipped == 0


# --- storage ---


def test_scout_stores_result_in_context_store(tmp_path):
    store = make_store(tmp_path)
    src = tmp_path / "d.py"
    src.write_text(SAMPLE_SOURCE)
    path = str(src)

    asyncio.run(scout_files([path], store, make_llm_client("summary here")))

    saved = store.get_summary(path)
    assert saved is not None
    assert saved.summary == "summary here"
    assert saved.content_hash == Sourcer.hash(SAMPLE_SOURCE)


# --- ScoutResult fields ---


def test_scout_result_tokens_used_nonzero(tmp_path):
    store = make_store(tmp_path)
    src = tmp_path / "e.py"
    src.write_text(SAMPLE_SOURCE)

    result = asyncio.run(scout_files([str(src)], store, make_llm_client()))

    assert result.tokens_used > 0


def test_scout_result_tokens_zero_on_all_hits(tmp_path):
    store = make_store(tmp_path)
    src = tmp_path / "f.py"
    src.write_text(SAMPLE_SOURCE)
    path = str(src)
    store.set_summary(path, FileSummary(path=path, summary="x", content_hash=Sourcer.hash(SAMPLE_SOURCE)))

    result = asyncio.run(scout_files([path], store, make_llm_client()))

    assert result.tokens_used == 0


# --- progress callback ---


def test_scout_progress_cb_called_for_every_file(tmp_path):
    store = make_store(tmp_path)
    hit = tmp_path / "hit.py"
    miss = tmp_path / "miss.py"
    hit.write_text(SAMPLE_SOURCE)
    miss.write_text(SAMPLE_SOURCE)
    hit_path = str(hit)
    store.set_summary(hit_path, FileSummary(path=hit_path, summary="x", content_hash=Sourcer.hash(SAMPLE_SOURCE)))

    calls: list[str] = []
    asyncio.run(scout_files([hit_path, str(miss)], store, make_llm_client(), progress_cb=calls.append))

    assert len(calls) == 2


def test_scout_no_progress_cb_does_not_raise(tmp_path):
    store = make_store(tmp_path)
    src = tmp_path / "g.py"
    src.write_text(SAMPLE_SOURCE)

    asyncio.run(scout_files([str(src)], store, make_llm_client()))  # no progress_cb


# --- parallel gather ---


def test_scout_parallel_gather_all_misses(tmp_path):
    store = make_store(tmp_path)
    paths = []
    for i in range(3):
        p = tmp_path / f"p{i}.py"
        p.write_text(SAMPLE_SOURCE)
        paths.append(str(p))

    client = make_llm_client()
    result = asyncio.run(scout_files(paths, store, client))

    assert result.scouted == 3
    assert client.with_structured_output.return_value.ainvoke.await_count == 3


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
