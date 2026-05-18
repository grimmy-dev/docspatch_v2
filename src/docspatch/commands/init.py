"""``dp init`` — interactive setup flow. Orchestration only."""

from pathlib import Path

from docspatch.context_store import ContextStore
from docspatch.pipelines.scout.pipeline import pre_build
from docspatch.ui import Prompter, QuestionaryPrompter, console
from docspatch.utils.config import ConfigStore, default_store
from docspatch.utils.selection import gather_selections, persist, select_license


def run(
    repo_root: Path | None = None,
    global_config_path: Path | None = None,
    reconfigure: bool = False,
    prompter: Prompter | None = None,
) -> None:
    """Full ``dp init`` flow.

    Args:
        repo_root: Repository root. Defaults to cwd.
        global_config_path: Override for ``~/.docspatch/config.toml``. Test seam.
        reconfigure: Re-prompt every field even if already set. Per-provider api
            keys remain on disk so switching providers does not lose stored keys.
        prompter: Interactive prompter. Defaults to :class:`QuestionaryPrompter`.
    """
    repo_root = repo_root or Path.cwd()
    p = prompter or QuestionaryPrompter()
    store = resolve_store(repo_root, global_config_path)

    selections = gather_selections(store, p, reconfigure=reconfigure)
    select_license(repo_root, p, reconfigure=reconfigure)
    persist(store, selections)

    ctx_store = ContextStore(repo_root)
    ctx_store.ensure_gitignore()
    console.print("[green]✓[/green] .docspatch added to .gitignore")

    pre_build(repo_root, ctx_store, store, selections.provider, selections.api_key, p)


def resolve_store(repo_root: Path, global_config_path: Path | None) -> ConfigStore:
    if global_config_path is None:
        return default_store(repo_root)
    return ConfigStore(
        global_path=global_config_path,
        repo_path=repo_root / ".docspatch" / "config.toml",
    )
