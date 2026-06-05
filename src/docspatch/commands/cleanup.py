"""User command to interactive clear files, caches, and database folders."""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from docspatch.manifest import MANIFEST_NAME
from docspatch.ui import Prompter, QuestionaryPrompter, console, status
from docspatch.utils.logging import get_logger

log = get_logger("cleanup")


@dataclass
class CleanupItem:
    label: str
    path: Path


def cleanup_items(repo_root: Path) -> list[CleanupItem]:
    """Compile a list of deletable repository-specific artifacts.

    Args:
        repo_root: Path to the repository root directory.

    Returns:
        List of cleanup items.
    """
    home = Path.home()
    docspatch_dir = repo_root / ".docspatch"
    cache_root = docspatch_dir / "cache"
    checkpoints = docspatch_dir / "checkpoints"
    manifest = docspatch_dir / MANIFEST_NAME
    repo_cfg = docspatch_dir / "config.toml"
    global_dir = home / ".docspatch"
    return [
        CleanupItem(f"Caches{_path_hint(cache_root)}", cache_root),
        CleanupItem(f"Checkpoints{_path_hint(checkpoints)}", checkpoints),
        CleanupItem(f"Change manifest{_path_hint(manifest)}", manifest),
        CleanupItem(f"Repo config{_path_hint(repo_cfg)}", repo_cfg),
        CleanupItem(f"Global docspatch data (~/.docspatch){_path_hint(global_dir)}", global_dir),
    ]


def _path_hint(path: Path) -> str:
    """Create a display string for a path showing its size or indicating it is missing.

    Args:
        path: Target file or directory path.

    Returns:
        Descriptive string including file size or status.
    """
    if not path.exists():
        return " (absent)"
    if path.is_file():
        return f" ({_human_bytes(path.stat().st_size)})"
    return f" ({_human_bytes(_dir_bytes(path))})"


def _dir_bytes(root: Path) -> int:
    """Calculate the recursive sum of file sizes within a directory.

    Args:
        root: Target directory path.

    Returns:
        Total size in bytes.
    """
    total = 0
    for dirpath, _, files in os.walk(root):
        for f in files:
            try:
                total += (Path(dirpath) / f).stat().st_size
            except OSError:
                continue
    return total


def _human_bytes(n: int) -> str:
    """Format a byte integer into a readable string using binary units.

    Args:
        n: Byte integer to format.

    Returns:
        String representation in B, KB, MB, or GB.
    """
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.1f} GB"


def run(prompter: Prompter | None = None, repo_root: Path | None = None) -> None:
    """Delete user-selected repository artifacts and empty configuration directories after interactive confirmation.

    Args:
        prompter: Interactive prompt interface used to gather user confirmation and selections.
        repo_root: Base directory to scan for temporary artifacts, defaulting to the current working directory.
    """
    p = prompter or QuestionaryPrompter()
    root = repo_root or Path.cwd()
    with status("Scanning artifacts…"):
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

    log.debug("deleting %d selected item(s)", len(selected))
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
    """Remove .docspatch directories that remain empty after preceding cleanup actions.

    Args:
        roots: List of potential parent directories to check.
    """
    for root in roots:
        try:
            if root.is_dir() and not any(root.iterdir()):
                root.rmdir()
                console.print(f"Removed empty {root}")
        except OSError:
            continue
