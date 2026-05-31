"""Per-run context shared by the docs pipeline nodes, plus checkpoint helpers.

``GraphContext`` holds everything a node needs that does not belong in graph
state — heavy source bodies, the live generator, the progress bar handle.
"""

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from docspatch.cache import DocsCache
from docspatch.checkpoints.ledger import TokenLedger
from docspatch.pipelines.docs.generator import DocstringGenerator
from docspatch.pipelines.docs.planner import Target
from docspatch.pipelines.docs.state import GenKey
from docspatch.ui import Prompter
from docspatch.ui.progress import BarHandle

SwitchHandler = Callable[[DocstringGenerator], Awaitable[DocstringGenerator | None]]
"""Returns a replacement generator on exhaustion, or ``None`` to abort."""

ReviewHandler = Callable[[dict[str, Any]], dict[str, Any]]
"""Renders the review UI for one ``interrupt`` payload and returns the user's choice.

The payload carries ``entries`` (serialized docstrings), ``round`` and
``allow_rerun``; the returned dict carries ``accepted`` / ``rejected`` / ``rerun``
id lists, a ``feedback`` map and an ``aborted`` flag.
"""


class GraphContext:
    """Per-run shared state for graph nodes. Heavy source bodies live here, not state."""

    def __init__(
        self,
        generator: DocstringGenerator,
        sem: asyncio.Semaphore,
        repo_root: Path,
        tone: str,
        cache: DocsCache | None,
        provider: str,
        tier: str,
        prompter: Prompter | None,
        auto_confirm: bool,
        batch_token_limit: int,
        run_id: str,
        interactive: bool,
        call_timeout: float,
        ledger: TokenLedger,
    ) -> None:
        """Initialize the document generation context with configuration and dependencies.

        Args:
            generator: The docstring generator instance.
            sem: Semaphore for controlling concurrent requests.
            repo_root: Root path of the repository.
            tone: Desired tone for generated documentation.
            cache: Optional cache for existing documentation states.
            provider: Name of the LLM provider.
            tier: The selected performance tier.
            prompter: Interface for user interactions.
            auto_confirm: Flag to bypass manual confirmations.
            batch_token_limit: Maximum token count allowed per batch.
            run_id: Unique identifier for the current run.
            interactive: Boolean flag for interactive mode.
            call_timeout: Seconds before an LLM call times out.
            ledger: The token usage ledger.
        """
        self.generator = generator
        self.sem = sem
        self.repo_root = repo_root
        self.tone = tone
        self.cache = cache
        self.provider = provider
        self.tier = tier
        self.prompter = prompter
        self.auto_confirm = auto_confirm
        self.batch_token_limit = batch_token_limit
        self.run_id = run_id
        self.interactive = interactive
        self.call_timeout = call_timeout
        self.ledger = ledger
        self.full_targets: dict[GenKey, Target] = {}
        self.advance: BarHandle | None = None


async def load_metadata(saver: AsyncSqliteSaver, config: RunnableConfig) -> dict[str, Any]:
    """Return checkpoint metadata for ``config`` (empty dict when fresh)."""
    snap = await saver.aget_tuple(config)
    if snap is None:
        return {}
    return dict(snap.metadata or {})
