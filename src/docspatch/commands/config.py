"""``dp config`` — show merged config + set/unset individual keys."""

import dataclasses

from docspatch.ui import build_table, console
from docspatch.utils.config import ConfigStore, default_store, load_config
from docspatch.utils.logging import get_logger
from docspatch.utils.secrets import display_value

log = get_logger("config")


def current_store() -> ConfigStore:
    """Canonical ConfigStore for the running command. Test override hook."""
    return default_store()


def run() -> None:
    """Display the current merged configuration settings in a tabular format."""
    s = current_store()
    cfg = load_config(global_path=s.global_path, repo_path=s.repo_path)
    rows = [
        [field.name, display_value(field.name, getattr(cfg, field.name).value), getattr(cfg, field.name).scope]
        for field in dataclasses.fields(cfg)
    ]
    log.debug("showing merged config: %d key(s)", len(rows))
    console.print(build_table(["KEY", "VALUE", "SCOPE"], rows))


def run_set(key: str, value: str) -> None:
    """Set a single config key. Scope is inferred from the key."""
    log.debug("setting config key: %s", key)  # value omitted — may be a secret
    written = current_store().set(key, value)
    console.print(f"[green]✓[/green] {written.key} = {display_value(written.key, written.value)} ({written.scope})")
