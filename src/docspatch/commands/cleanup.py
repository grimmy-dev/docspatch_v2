"""dp cleanup command — interactive multi-select deletion of docspatch artefacts."""

import shutil
from dataclasses import dataclass
from pathlib import Path

import questionary

from docspatch.ui.console import console


@dataclass
class CleanupItem:
    label: str
    path: Path


def cleanup_items(repo_root: Path) -> list[CleanupItem]:
    home = Path.home()
    return [
        CleanupItem("Scout cache", repo_root / ".docspatch" / "cache"),
        CleanupItem("Function hashes", home / ".docspatch" / "hashes.json"),
        CleanupItem("Checkpoints", home / ".docspatch" / "checkpoints.db"),
        CleanupItem("Repo config", repo_root / ".docspatch" / "config.toml"),
        CleanupItem("Global config", home / ".docspatch" / "config.toml"),
    ]


def run() -> None:
    items = cleanup_items(Path.cwd())
    choices = [
        questionary.Choice(f"{item.label}  ({item.path})", value=item)
        for item in items
    ]

    selected = questionary.checkbox("Select items to delete:", choices=choices).ask()

    if not selected:
        console.print("[dim]Nothing selected.[/dim]")
        return

    confirmed = questionary.confirm(f"Delete {len(selected)} item(s)?").ask()
    if not confirmed:
        console.print("[dim]Cancelled.[/dim]")
        return

    for item in selected:
        if not item.path.exists():
            console.print(f"[dim]{item.label} not found at {item.path} — skipping.[/dim]")
            continue
        if item.path.is_dir():
            shutil.rmtree(item.path, ignore_errors=True)
        else:
            item.path.unlink(missing_ok=True)
        console.print(f"Deleted {item.path}")
