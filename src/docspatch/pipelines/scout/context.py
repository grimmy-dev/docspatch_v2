"""Define the operational context for file scouting. This module coordinates state, configuration, and transient resource dependencies."""

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager

from docspatch.cache import ScoutCache
from docspatch.llm import LLMClient
from docspatch.pipelines.scout.state import FileMiss

ProgressCb = Callable[[str], None]
Gate = AbstractAsyncContextManager[object]
SwitchHandler = Callable[[LLMClient], Awaitable[LLMClient | None]]
"""Async callback. Takes the exhausted client, returns a new one or None to abort."""


class ScoutContext:
    """Shared state for scout graph nodes. File bodies live here, not in state."""

    def __init__(
        self,
        client: LLMClient,
        misses: dict[str, FileMiss],
        cache: ScoutCache,
        gate: Gate,
        progress_cb: ProgressCb | None,
        call_timeout: float,
    ) -> None:
        """Establish the scouting configuration and operational dependencies.

        Args:
            client: LLM client for analysis.
            misses: Files needing evaluation.
            cache: Cache store for scout results.
            gate: Semaphore for concurrency limiting.
        """
        self.client = client
        self.misses = misses
        self.cache = cache
        self.gate = gate
        self.progress_cb = progress_cb
        self.call_timeout = call_timeout
