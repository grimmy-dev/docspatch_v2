"""Defines the shared execution context for the docstring generation pipeline and provides utilities to fetch state metadata."""

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from docspatch.checkpoints.ledger import TokenLedger
from docspatch.pipelines.docs.generator import DocstringGenerator
from docspatch.pipelines.docs.registry import TargetRegistry
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
        prev_stamps: dict[str, tuple[int, int]],
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
        """Initialize the pipeline execution context with model settings, caches, and concurrency semaphores.

        Args:
            generator: The generator instance that orchestrates prompt creation.
            sem: The concurrency semaphore throttling raw API requests.
            repo_root: The absolute path to the repository directory.
            tone: The desired docstring style description.
            prev_stamps: The timestamp dictionary for baseline checks.
            provider: The name of the LLM provider service.
            tier: The rate-limit bucket designation.
            prompter: The interactive CLI promoter helper.
            auto_confirm: Flag to skip manual verification prompts.
            batch_token_limit: The limit of tokens allowed per pipeline batch.
            run_id: The unique execution session run identifier.
            interactive: Whether the process permits active terminal interaction.
            call_timeout: The maximum lifespan of a single model request in seconds.
            ledger: The ledger tracking total token usage.
        """
        self.generator = generator
        self.sem = sem
        self.repo_root = repo_root
        self.tone = tone
        # Stat stamps from the last successful docs run, for planner fast-skip.
        self.prev_stamps = prev_stamps
        self.provider = provider
        self.tier = tier
        self.prompter = prompter
        self.auto_confirm = auto_confirm
        self.batch_token_limit = batch_token_limit
        self.run_id = run_id
        self.interactive = interactive
        self.call_timeout = call_timeout
        self.ledger = ledger
        # Heavy bodies + plan-time hashes, set once by the plan node. Read access
        # before planning is a wiring bug, so the property below fails fast.
        self._registry: TargetRegistry | None = None
        self.advance: BarHandle | None = None

    @property
    def registry(self) -> TargetRegistry:
        """Return the plan-time target registry.

        Raises:
            RuntimeError: A node read the registry before the plan node built it.
        """
        if self._registry is None:
            raise RuntimeError("target registry read before planning")
        return self._registry

    @registry.setter
    def registry(self, value: TargetRegistry) -> None:
        self._registry = value


async def load_metadata(saver: AsyncSqliteSaver, config: RunnableConfig) -> dict[str, Any]:
    """Fetch state metadata for a specific runnable thread configuration from the checkpointer.

    Args:
        saver: The AsyncSqliteSaver checkpoint manager.
        config: The thread execution configuration.

    Returns:
        The metadata dictionary.
    """
    snap = await saver.aget_tuple(config)
    if snap is None:
        return {}
    return dict(snap.metadata or {})
