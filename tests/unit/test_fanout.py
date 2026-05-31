"""Behaviour of the shared fan-out runner: completion, re-issue, exhaustion, abort.

Drives a real ``build_fanout_graph`` through an in-memory checkpointer with a fake
worker, so the re-issue/switch loop is exercised without any LLM. Both pipelines
inherit these semantics from ``run_fanout``.
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from operator import add
from typing import Annotated, Any, TypedDict

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from docspatch.checkpoints.saver import make_serde
from docspatch.pipelines.fanout import build_fanout_graph, run_fanout
from docspatch.pipelines.scout.state import ScoutBatch
from docspatch.utils.errors import TransientExhausted


class _State(TypedDict, total=False):
    batches: list[ScoutBatch]
    completed_batches: Annotated[list[int], add]
    results: Annotated[list[int], add]


def _payload(_state: dict[str, Any], batch: ScoutBatch) -> dict[str, Any]:
    return {"batch": batch}


def _make_worker(fail_ids: frozenset[int] = frozenset()) -> Callable[[dict[str, Any]], Awaitable[_State]]:
    """Node that completes each batch, except ids in ``fail_ids`` on their first attempt."""
    seen: set[int] = set()

    async def worker(payload: dict[str, Any]) -> _State:
        batch: ScoutBatch = payload["batch"]
        first_attempt = batch.id not in seen
        seen.add(batch.id)
        if first_attempt and batch.id in fail_ids:
            return {}  # leave unmarked → still unfinished
        return {"completed_batches": [batch.id], "results": [batch.id]}

    return worker


async def _run(
    worker: Callable[[dict[str, Any]], Awaitable[_State]],
    batches: list[ScoutBatch],
    switch: Callable[[], Awaitable[bool]] | None,
    *,
    label: str = "test",
    on_wave: Callable[[int, dict[str, Any], Sequence[ScoutBatch]], None] | None = None,
) -> dict[str, Any]:
    async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
        saver.serde = make_serde()
        graph = build_fanout_graph(_State, "work", worker, _payload, saver)
        config = {"configurable": {"thread_id": "t1"}}
        return await run_fanout(
            graph, saver, config, initial={"batches": batches}, pending=batches, switch=switch, label=label, on_wave=on_wave
        )


def _batches(n: int) -> list[ScoutBatch]:
    return [ScoutBatch(id=i, paths=[]) for i in range(n)]


def test_all_batches_complete_in_one_wave() -> None:
    final = asyncio.run(_run(_make_worker(), _batches(3), switch=None))
    assert set(final["completed_batches"]) == {0, 1, 2}
    assert sorted(final["results"]) == [0, 1, 2]


def test_switch_reissues_only_unfinished_batch() -> None:
    switches: list[int] = []
    waves: list[tuple[int, list[int]]] = []

    async def switch() -> bool:
        switches.append(1)
        return True

    def on_wave(wave: int, _current: dict[str, Any], remaining: Sequence[ScoutBatch]) -> None:
        waves.append((wave, [b.id for b in remaining]))

    final = asyncio.run(_run(_make_worker(fail_ids=frozenset({1})), _batches(3), switch, on_wave=on_wave))

    assert set(final["completed_batches"]) == {0, 1, 2}
    assert switches == [1]  # exactly one switch
    assert waves == [(1, [1])]  # second wave re-issued only batch 1


def test_exhaustion_without_switch_raises() -> None:
    with pytest.raises(TransientExhausted, match="scout exhausted"):
        asyncio.run(_run(_make_worker(fail_ids=frozenset({0})), _batches(1), switch=None, label="scout"))


def test_switch_abort_keeps_partial_state() -> None:
    async def switch() -> bool:
        return False  # give up after exhaustion

    final = asyncio.run(_run(_make_worker(fail_ids=frozenset({1})), _batches(2), switch))

    assert final.get("completed_batches", []) == [0]  # batch 1 never finished
