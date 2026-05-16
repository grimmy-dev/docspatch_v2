"""dp config command — merged config display with scope labels."""

import dataclasses
from pathlib import Path

from rich.table import Table

from docspatch.ui.console import console
from docspatch.utils.config import load_config


def mask_api_key(value: object) -> str:
    """Mask all but the first 4 characters of an API key."""
    if not value:
        return "—"
    s = str(value)
    return (s[:4] + "••••••••") if len(s) > 4 else "••••••••"


def run() -> None:
    cfg = load_config(
        global_path=Path.home() / ".docspatch" / "config.toml",
        repo_path=Path.cwd() / ".docspatch" / "config.toml",
    )

    table = Table(show_header=True, header_style="bold")
    table.add_column("KEY")
    table.add_column("VALUE")
    table.add_column("SCOPE")

    for field in dataclasses.fields(cfg):
        scoped = getattr(cfg, field.name)
        display = mask_api_key(scoped.value) if field.name == "api_key" else str(scoped.value) if scoped.value is not None else "—"
        table.add_row(field.name, display, scoped.scope)

    console.print(table)
