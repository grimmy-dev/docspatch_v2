"""Renders a shallow directory tree as indented text for README context."""

from pathlib import Path


def get_dir_tree(root: Path, max_depth: int = 3) -> str:
    """Generate a text representation of the directory structure down to a maximum depth.

    Args:
        root: Starting path to traverse.
        max_depth: Maximum levels of subdirectory expansion.

    Returns:
        Formatted directory tree string.
    """
    lines: list[str] = []
    _walk(root, max_depth, 0, lines)
    return "\n".join(lines)


def _walk(current: Path, max_depth: int, depth: int, lines: list[str]) -> None:
    """Traverse subdirectories recursively to construct directory tree lines.

    Args:
        current: Current directory path in the loop.
        max_depth: Limit of recursion depth.
        depth: Active recursion depth.
        lines: Buffer list collecting formatted directory lines.
    """
    if depth > max_depth:
        return
    for entry in sorted(current.iterdir()):
        if entry.name.startswith("."):
            continue
        indent = "  " * depth
        lines.append(f"{indent}{entry.name}")
        if entry.is_dir() and depth < max_depth:
            _walk(entry, max_depth, depth + 1, lines)
