"""Per-run context for scout graph nodes, plus the checkpoint state helper.

``ScoutContext`` holds what nodes need but must not enter graph state: the live
client, the file bodies, the concurrency gate, the progress callback.
"""

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

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
        """Initialize the scouting context with necessary dependencies.

        Args:
            client: The LLM client instance.
            misses: Dictionary of file misses requiring analysis.
            cache: The scout cache instance.
            gate: The rate limit gate.
            progress_cb: Optional callback for reporting progress.
            call_timeout: Time limit for LLM requests.
        """
        self.client = client
        self.misses = misses
        self.cache = cache
        self.gate = gate
        self.progress_cb = progress_cb
        self.call_timeout = call_timeout


async def load_state(saver: AsyncSqliteSaver, config: RunnableConfig) -> dict:
    """Return last-committed state values for ``config``; empty dict when fresh."""
    snap = await saver.aget_tuple(config)
    if snap is None or snap.checkpoint is None:
        return {}
    return dict(snap.checkpoint.get("channel_values", {}))
