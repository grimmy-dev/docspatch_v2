"""dp cleanup command — interactive multi-select deletion of docspatch artefacts."""

import shutil
from dataclasses import dataclass
from pathlib import Path

from docspatch.ui import Prompter, QuestionaryPrompter, console


@dataclass
class CleanupItem:
    label: str
    path: Path


def cleanup_items(repo_root: Path) -> list[CleanupItem]:
    home = Path.home()
    return [
        CleanupItem("Caches", repo_root / ".docspatch" / "cache"),
        CleanupItem("Checkpoints", repo_root / ".docspatch" / "checkpoints"),
        CleanupItem("Repo config", repo_root / ".docspatch" / "config.toml"),
        CleanupItem("Global docspatch data (~/.docspatch)", home / ".docspatch"),
    ]


def run(prompter: Prompter | None = None, repo_root: Path | None = None) -> None:
    p = prompter or QuestionaryPrompter()
    root = repo_root or Path.cwd()
    items = cleanup_items(root)
    choices = {f"{item.label}  ({item.path})": item for item in items}

    raw = p.checkbox("Select items to delete:", choices)
    selected: list[CleanupItem] = [c for c in raw if isinstance(c, CleanupItem)]

    if not selected:
        console.print("[dim]Nothing selected.[/dim]")
        return

    if not p.confirm(f"Delete {len(selected)} item(s)?"):
        console.print("[dim]Cancelled.[/dim]")
        return

    for item in selected:
        if item.path.is_dir():
            shutil.rmtree(item.path, ignore_errors=True)
            console.print(f"Deleted {item.path}")
        else:
            try:
                item.path.unlink()
                console.print(f"Deleted {item.path}")
            except FileNotFoundError:
                console.print(f"[dim]{item.label} not found at {item.path} — skipping.[/dim]")

    sweep_empty_docspatch_dirs([root / ".docspatch", Path.home() / ".docspatch"])


def sweep_empty_docspatch_dirs(roots: list[Path]) -> None:
    """Remove ``.docspatch`` dirs that are empty after deletions. Idempotent."""
    for root in roots:
        try:
            if root.is_dir() and not any(root.iterdir()):
                root.rmdir()
                console.print(f"Removed empty {root}")
        except OSError:
            continue
