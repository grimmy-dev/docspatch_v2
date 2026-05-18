"""RunContext — pipeline-scoped dependency holder constructed before any dp run."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field

from docspatch.context_store import ContextStore
from docspatch.llm import LLMClient
from docspatch.pipelines.scout import ScoutResult, scout_files
from docspatch.types.config import DocspatchConfig


@dataclass
class RunContext:
    """Holds all dependencies for a single dp pipeline run.

    State for LangGraph nodes is intentionally not held here — nodes look up
    summaries by path against `ctx_store`. Keeps graph state cheap.
    """

    llm_client: LLMClient
    ctx_store: ContextStore
    config: DocspatchConfig
    progress_cb: Callable[[str], None] | None = field(default=None)
    _semaphore: asyncio.Semaphore | None = field(default=None, init=False, repr=False)

    @property
    def semaphore(self) -> asyncio.Semaphore:
        """Bounded fan-out for LLM calls. Created on first access (event loop safe)."""
        if self._semaphore is None:
            limit = max(1, int(self.config.concurrency_limit.value or 1))
            self._semaphore = asyncio.Semaphore(limit)
        return self._semaphore

    def progress(self, message: str) -> None:
        if self.progress_cb:
            self.progress_cb(message)

    async def scout(self, paths: list[str]) -> ScoutResult:
        return await scout_files(
            paths,
            self.ctx_store,
            self.llm_client,
            progress_cb=self.progress_cb,
            semaphore=self.semaphore,
            batch_token_limit=int(self.config.batch_token_limit.value or 6000),
        )
