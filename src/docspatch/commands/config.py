"""``dp config`` — show merged config + set/unset individual keys."""

import dataclasses

from docspatch.ui import build_table, console
from docspatch.utils.config import ConfigStore, default_store, load_config
from docspatch.utils.secrets import display_value


def current_store() -> ConfigStore:
    """Canonical ConfigStore for the running command. Test override hook."""
    return default_store()


def run() -> None:
    s = current_store()
    cfg = load_config(global_path=s.global_path, repo_path=s.repo_path)
    rows = [
        [field.name, display_value(field.name, getattr(cfg, field.name).value), getattr(cfg, field.name).scope]
        for field in dataclasses.fields(cfg)
    ]
    console.print(build_table(["KEY", "VALUE", "SCOPE"], rows))


def run_set(key: str, value: str) -> None:
    """Set a single config key. Scope is inferred from the key."""
    written = current_store().set(key, value)
    console.print(f"[green]✓[/green] {written.key} = {display_value(written.key, written.value)} ({written.scope})")
