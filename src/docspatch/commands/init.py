"""CLI command for initializing workspace configuration, license choices, and project environment settings."""

from pathlib import Path

from docspatch.ui import Prompter, QuestionaryPrompter, console, status
from docspatch.utils.config import ConfigStore, default_store
from docspatch.utils.ignore import ensure_docspatch_ignored
from docspatch.utils.logging import get_logger
from docspatch.utils.selection import ensure_configured, select_license

log = get_logger("init")


def run(
    repo_root: Path | None = None,
    global_config_path: Path | None = None,
    reconfigure: bool = False,
    prompter: Prompter | None = None,
) -> None:
    """Walk the user through configuring API providers, keys, and documentation licenses.

    Args:
        repo_root: Local directory where settings will be saved.
        global_config_path: Optional file path overrides for global configurations.
        reconfigure: Force prompt inputs even if configuration already exists.
        prompter: Custom prompt interface to gather inputs.
    """
    repo_root = repo_root or Path.cwd()
    p = prompter or QuestionaryPrompter()
    store = resolve_store(repo_root, global_config_path)

    # Deferred so a bare `dp`/`--help` never pays the provider-SDK import cost.
    with status("Starting up…"):
        from docspatch.llm import validate_api_key

    log.debug("init starting for repo: %s", repo_root)
    selections = ensure_configured(store, p, validate_api_key, reconfigure=reconfigure)
    select_license(repo_root, p, reconfigure=reconfigure)
    log.debug("config + license resolved; provider=%s", selections.provider)

    ensure_docspatch_ignored(repo_root)
    console.print("[green]✓[/green] .docspatch added to .gitignore")
    console.print("[green]✓[/green] docspatch is ready. Run `dp docs` to document code or `dp readme` to generate a README.")


def resolve_store(repo_root: Path, global_config_path: Path | None) -> ConfigStore:
    """Load the ConfigStore using the provided or default global paths.

    Args:
        repo_root: Local workspace directory path.
        global_config_path: Alternative file path for the global configuration file.

    Returns:
        A ConfigStore loaded with regional settings.
    """
    if global_config_path is None:
        return default_store(repo_root)
    return ConfigStore(
        global_path=global_config_path,
        repo_path=repo_root / ".docspatch" / "config.toml",
    )
