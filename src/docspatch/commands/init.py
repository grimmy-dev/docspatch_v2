"""Handle repository initialization and configuration setup."""

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
    """Run the complete initialization flow.

    Args:
        repo_root: Path to the target repository.
        global_config_path: Override for the global config file.
        reconfigure: Force re-prompting of settings.
        prompter: Interface for user interaction.
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
    """Construct a configuration store based on local and global path inputs.

    Args:
        repo_root: Path to the repository root.
        global_config_path: Custom location for global configuration.

    Returns:
        Configured store instance.
    """
    if global_config_path is None:
        return default_store(repo_root)
    return ConfigStore(
        global_path=global_config_path,
        repo_path=repo_root / ".docspatch" / "config.toml",
    )
