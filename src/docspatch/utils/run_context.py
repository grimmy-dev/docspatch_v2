"""RunContext — pipeline-scoped dependency holder constructed before any dp run."""

from collections.abc import Callable
from dataclasses import dataclass, field

from docspatch.cache import ScoutCache
from docspatch.constants import DEFAULT_BATCH_TOKEN_LIMIT, DEFAULT_CALL_TIMEOUT, DEFAULT_CONCURRENCY_LIMIT
from docspatch.llm import LLMClient
from docspatch.pipelines.scout.graph import run_scout
from docspatch.pipelines.scout.state import ScoutResult
from docspatch.types.config import DocspatchConfig


@dataclass
class RunContext:
    """Holds all dependencies for a single dp pipeline run.

    State for LangGraph nodes is intentionally not held here — nodes look up
    summaries by path against `ctx_store`. Keeps graph state cheap.
    """

    llm_client: LLMClient
    ctx_store: ScoutCache
    config: DocspatchConfig
    progress_cb: Callable[[str], None] | None = field(default=None)

    def progress(self, message: str) -> None:
        if self.progress_cb:
            self.progress_cb(message)

    async def scout(self, paths: list[str]) -> ScoutResult:
        return await run_scout(
            paths,
            self.ctx_store,
            self.llm_client,
            progress_cb=self.progress_cb,
            batch_token_limit=int(self.config.batch_token_limit.value or DEFAULT_BATCH_TOKEN_LIMIT),
            concurrency_limit=int(self.config.concurrency_limit.value or DEFAULT_CONCURRENCY_LIMIT),
            call_timeout=float(self.config.call_timeout.value or DEFAULT_CALL_TIMEOUT),
        )
