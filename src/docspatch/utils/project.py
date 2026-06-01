"""Provide utilities for extracting metadata and filesystem structures from a project."""

import tomllib
from pathlib import Path


def get_pyproject_field(pyproject_path: Path, field: str) -> str | None:
    """Return the value of a [project] field, or None if absent or file missing.

    Args:
        pyproject_path: Path to the pyproject.toml file.
        field: Name of the key to look up.

    Returns:
        The field value as a string, or null.
    """
    if not pyproject_path.exists():
        return None
    try:
        data = tomllib.loads(pyproject_path.read_text())
    except tomllib.TOMLDecodeError, OSError:
        return None
    value = data.get("project", {}).get(field)
    return str(value) if value is not None else None


def get_dir_tree(root: Path, max_depth: int = 3) -> str:
    """Return a text directory tree up to max_depth levels deep.

    Args:
        root: Root directory to start walking from.
        max_depth: Maximum levels of the hierarchy to display.

    Returns:
        The directory tree structure.
    """
    lines: list[str] = []
    _walk(root, root, max_depth, 0, lines)
    return "\n".join(lines)


def _walk(root: Path, current: Path, max_depth: int, depth: int, lines: list[str]) -> None:
    """Recursively walk the file system to display project structure.

    Args:
        root: Base directory for the traversal.
        current: Current directory being processed.
        max_depth: Limit of recursion depth.
        depth: Current recursion depth.
        lines: List of strings collecting the directory tree lines.
    """
    if depth > max_depth:
        return
    for entry in sorted(current.iterdir()):
        if entry.name.startswith("."):
            continue
        indent = "  " * depth
        lines.append(f"{indent}{entry.name}")
        if entry.is_dir() and depth < max_depth:
            _walk(root, entry, max_depth, depth + 1, lines)
