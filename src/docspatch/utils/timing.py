"""Command clock and budget watchdog.

Wall time since the command started drives the on-screen timer; active time
(wall minus time spent waiting on a human) drives the budget that aborts a
stuck run.
"""

import asyncio
import time
from collections.abc import Awaitable, Iterator
from contextlib import contextmanager

from docspatch.utils.errors import RunTimeout

RUN_BUDGET_SECONDS = 600.0
"""Cap on active (non-prompt) automated work before a run is aborted."""


class RunClock:
    """Monotonic clock for one command run.

    ``wall_elapsed`` counts every second since ``start``; ``active_elapsed``
    subtracts the spans spent paused on interactive prompts.
    """

    def __init__(self) -> None:
        """Create an unstarted clock."""
        self._start: float | None = None
        self._paused_total = 0.0
        self._paused_at: float | None = None

    def start(self) -> None:
        """Begin (or restart) timing from now."""
        self._start = time.monotonic()
        self._paused_total = 0.0
        self._paused_at = None

    def wall_elapsed(self) -> float:
        """Return seconds since ``start``, or 0 before the clock starts."""
        return 0.0 if self._start is None else time.monotonic() - self._start

    def active_elapsed(self) -> float:
        """Return seconds of active work, excluding paused prompt spans."""
        if self._start is None:
            return 0.0
        held = self._paused_total + (time.monotonic() - self._paused_at if self._paused_at is not None else 0.0)
        return time.monotonic() - self._start - held

    @contextmanager
    def paused(self) -> Iterator[None]:
        """Stop counting active time while a human is being waited on."""
        if self._start is None or self._paused_at is not None:
            yield
            return
        self._paused_at = time.monotonic()
        try:
            yield
        finally:
            if self._paused_at is not None:
                self._paused_total += time.monotonic() - self._paused_at
                self._paused_at = None


clock = RunClock()
"""Process-wide command clock; one command runs at a time."""


def format_duration(seconds: float) -> str:
    """Format a duration as ``12s`` or ``3m04s``.

    Args:
        seconds: The duration in seconds.

    Returns:
        A compact human-readable string.
    """
    secs = int(seconds)
    return f"{secs}s" if secs < 60 else f"{secs // 60}m{secs % 60:02d}s"


async def run_within_budget[T](coro: Awaitable[T], budget: float = RUN_BUDGET_SECONDS) -> T:
    """Run a coroutine under the active-time budget, aborting if it overruns.

    The watchdog measures active time, so seconds spent waiting on interactive
    prompts (wrapped in ``clock.paused()``) never count against the budget.

    Args:
        coro: The coroutine to run.
        budget: Active-work budget in seconds.

    Returns:
        The coroutine's result.

    Raises:
        RunTimeout: Active work exceeded the budget.
    """
    task: asyncio.Task[T] = asyncio.ensure_future(coro)
    expired = False
    interval = min(1.0, max(budget / 5, 0.02))

    async def watch() -> None:
        nonlocal expired
        while not task.done():
            await asyncio.sleep(interval)
            if clock.active_elapsed() > budget:
                expired = True
                task.cancel()
                return

    watcher = asyncio.ensure_future(watch())
    try:
        return await task
    except asyncio.CancelledError:
        if expired:
            raise RunTimeout.exceeded(budget) from None
        raise
    finally:
        watcher.cancel()
