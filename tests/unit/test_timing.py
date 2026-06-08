"""RunClock pause accounting, duration formatting, and the budget watchdog."""

import asyncio
import time

import pytest

from docspatch.utils.errors import RunTimeout
from docspatch.utils.timing import RunClock, format_duration, run_within_budget


def test_active_elapsed_excludes_paused_span() -> None:
    c = RunClock()
    c.start()
    with c.paused():
        time.sleep(0.05)
    # Wall time advanced, but the paused span is not counted as active work.
    assert c.wall_elapsed() >= 0.05
    assert c.active_elapsed() < 0.05


def test_unstarted_clock_reads_zero() -> None:
    c = RunClock()
    assert c.wall_elapsed() == 0.0
    assert c.active_elapsed() == 0.0


def test_format_duration_under_and_over_a_minute() -> None:
    assert format_duration(12) == "12s"
    assert format_duration(63) == "1m03s"


def test_run_within_budget_returns_result() -> None:
    async def work() -> int:
        return 42

    assert asyncio.run(run_within_budget(work(), budget=5.0)) == 42


def test_run_within_budget_aborts_when_overrun() -> None:
    from docspatch.utils.timing import clock

    async def go() -> None:
        clock.start()
        await run_within_budget(asyncio.sleep(5), budget=0.1)

    with pytest.raises(RunTimeout):
        asyncio.run(go())
