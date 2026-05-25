"""dp cleanup command — interactive multi-select deletion of docspatch artefacts."""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from docspatch.cache import DocsCache, ScoutCache
from docspatch.ui import Prompter, QuestionaryPrompter, console


@dataclass
class CleanupItem:
    label: str
    path: Path


def cleanup_items(repo_root: Path) -> list[CleanupItem]:
    """Cleanup tasks for the current repo. Labels include size hints when present."""
    home = Path.home()
    cache_root = repo_root / ".docspatch" / "cache"
    checkpoints = repo_root / ".docspatch" / "checkpoints"
    repo_cfg = repo_root / ".docspatch" / "config.toml"
    global_dir = home / ".docspatch"
    return [
        CleanupItem(f"Caches{_cache_hint(repo_root)}", cache_root),
        CleanupItem(f"Checkpoints{_path_hint(checkpoints)}", checkpoints),
        CleanupItem(f"Repo config{_path_hint(repo_cfg)}", repo_cfg),
        CleanupItem(f"Global docspatch data (~/.docspatch){_path_hint(global_dir)}", global_dir),
    ]


def _cache_hint(repo_root: Path) -> str:
    """`` (N files, X)`` summed across docs + scout caches. Empty when both empty."""
    docs, scout = DocsCache(repo_root).info(), ScoutCache(repo_root).info()
    count = docs.file_count + scout.file_count
    if count == 0:
        return ""
    return f" ({count} files, {_human_bytes(docs.total_size_bytes + scout.total_size_bytes)})"


def _path_hint(path: Path) -> str:
    """`` (X)`` for a file/dir, `` (absent)`` when missing."""
    if not path.exists():
        return " (absent)"
    if path.is_file():
        return f" ({_human_bytes(path.stat().st_size)})"
    return f" ({_human_bytes(_dir_bytes(path))})"


def _dir_bytes(root: Path) -> int:
    """Recursive byte total under ``root``. Skips unreadable entries."""
    total = 0
    for dirpath, _, files in os.walk(root):
        for f in files:
            try:
                total += (Path(dirpath) / f).stat().st_size
            except OSError:
                continue
    return total


def _human_bytes(n: int) -> str:
    """``1.2 MB`` / ``45 KB`` / ``321 B``."""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.1f} GB"


def run(prompter: Prompter | None = None, repo_root: Path | None = None) -> None:
    """Execute the interactive cleanup process for repository-specific data.

    Args:
        prompter: Optional interface for handling user prompts.
        repo_root: Optional path to the repository root directory.
    """
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
