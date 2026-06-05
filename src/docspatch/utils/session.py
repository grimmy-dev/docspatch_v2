"""Manages runtime session initialization, configuration loading, LLM client assembly, and connection checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import typer

from docspatch.llm import tier_for_model
from docspatch.ui import Prompter, console, status
from docspatch.utils.config import default_store
from docspatch.utils.logging import get_logger
from docspatch.utils.selection import ensure_configured

if TYPE_CHECKING:
    from pathlib import Path

    from docspatch.llm import LLMClient
    from docspatch.llm.client import RetryCallback
    from docspatch.utils.config import ConfigStore
    from docspatch.utils.selection import Selections

log = get_logger("session")


@dataclass(frozen=True)
class Session:
    """Resolved provider config for one run: store, selections, generator tier."""

    store: ConfigStore
    selections: Selections
    tier: str

    @property
    def provider(self) -> str:
        """Access the active LLM provider name from the session configuration.

        Returns:
            The active provider identifier.
        """
        return self.selections.provider


def load_session(repo_root: Path, prompter: Prompter) -> Session:
    """Load the configuration store from the repository root, resolve interactive selections, and return a Session instance.

    Args:
        repo_root: Path to the local repository root.
        prompter: Interface for user terminal interactions.

    Returns:
        A runtime Session initialized with resolved configuration selections.
    """
    def validate(provider: str, key: str) -> bool:
        # Lazy so the common "already configured" path never imports the SDK; the
        # import only lands when a new key is actually entered and validated.
        from docspatch.llm import validate_api_key

        return validate_api_key(provider, key)

    store = default_store(repo_root)
    log.debug("loading config under %s", repo_root)
    selections = ensure_configured(store, prompter, validate)
    tier = tier_for_model(selections.provider, selections.generator_model)
    log.debug(
        "config ready: provider=%s generator=%s tier=%s tone=%s",
        selections.provider,
        selections.generator_model,
        tier,
        selections.tone,
    )
    return Session(store=store, selections=selections, tier=tier)


def verify_connection(session: Session) -> None:
    """Test the provider connection by calling key validation using a fast model tier.

    Args:
        session: The active runtime configuration session.

    Raises:
        typer.Exit: The provider rejects the API key or connection fails.
    """
    from docspatch.llm import LLMClient

    provider = session.provider
    with status(f"Connecting to {provider}…"):
        ok = LLMClient(provider=provider, api_key=session.selections.api_key, generator_tier="fast").validate_key()
    if not ok:
        console.print(f"[red]✗[/red] Could not connect to {provider}. Check your API key with `dp init --reconfigure`.")
        raise typer.Exit(1)
    console.print(f"[green]✓[/green] Connected to {provider}.")
    log.debug("connection verified: provider=%s", provider)


def client_for(session: Session, tier: str | None = None, *, retry_cb: RetryCallback | None = None) -> LLMClient:
    """Construct an LLM client configured for a specific tier and optional retry callback.

    Args:
        session: The active runtime configuration session.
        tier: LLM tier override; defaults to the session's generator tier.
        retry_cb: Optional callback for custom retry actions.

    Returns:
        An LLM client instance ready for network requests.
    """
    from docspatch.llm import LLMClient

    resolved = tier or session.tier
    log.debug("building client: provider=%s tier=%s", session.provider, resolved)
    return LLMClient(provider=session.provider, api_key=session.selections.api_key, generator_tier=resolved, retry_cb=retry_cb)
