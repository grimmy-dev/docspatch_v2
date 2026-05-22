"""``dp init`` — interactive setup flow. Orchestration only."""

from pathlib import Path

from docspatch.cache import ScoutCache
from docspatch.pipelines.scout.pipeline import pre_build
from docspatch.ui import Prompter, QuestionaryPrompter, console
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

    log.debug("init starting for repo: %s", repo_root)
    selections = ensure_configured(store, p, reconfigure=reconfigure)
    select_license(repo_root, p, reconfigure=reconfigure)
    log.debug("config + license resolved; provider=%s", selections.provider)

    ctx_store = ScoutCache(repo_root)
    ensure_docspatch_ignored(repo_root)
    console.print("[green]✓[/green] .docspatch added to .gitignore")

    log.debug("starting scout pre-build")
    pre_build(repo_root, ctx_store, store, selections.provider, selections.api_key, p)


def resolve_store(repo_root: Path, global_config_path: Path | None) -> ConfigStore:
    if global_config_path is None:
        return default_store(repo_root)
    return ConfigStore(
        global_path=global_config_path,
        repo_path=repo_root / ".docspatch" / "config.toml",
    )
