"""RunContext — pipeline-scoped dependency holder constructed before any dp run."""

from collections.abc import Callable
from dataclasses import dataclass, field

from docspatch.context_store import ContextStore
from docspatch.llm_client import LLMClient
from docspatch.scout import ScoutResult, scout_files
from docspatch.types.config import DocspatchConfig


@dataclass
class RunContext:
    """Holds all dependencies for a single dp pipeline run."""

    llm_client: LLMClient
    ctx_store: ContextStore
    config: DocspatchConfig
    progress_cb: Callable[[str], None] | None = field(default=None)

    def progress(self, message: str) -> None:
        if self.progress_cb:
            self.progress_cb(message)

    async def scout(self, paths: list[str]) -> ScoutResult:
        return await scout_files(paths, self.ctx_store, self.llm_client, self.progress_cb)
