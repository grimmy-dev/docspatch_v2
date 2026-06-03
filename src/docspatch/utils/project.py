"""Provide utilities for extracting metadata and filesystem structures from a project."""

import tomllib
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path


@dataclass(frozen=True)
class ProjectFacts:
    """Deterministic project metadata read from pyproject.toml.

    ``name`` always has a value (falls back to the repo directory name); every
    other field is present only when pyproject supplied it, so nothing null is
    ever rendered.
    """

    name: str
    description: str | None = None
    labelled: list[tuple[str, str]] = dc_field(default_factory=list)


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


def project_facts(repo_root: Path) -> ProjectFacts:
    """Collect generic project metadata from pyproject.toml, omitting absent fields.

    Args:
        repo_root: The repository root containing pyproject.toml.

    Returns:
        Facts with a guaranteed name and only the labelled fields that exist.
    """
    pyproject = repo_root / "pyproject.toml"
    try:
        project = tomllib.loads(pyproject.read_text()).get("project", {})
    except (tomllib.TOMLDecodeError, OSError):
        project = {}

    def field_str(key: str) -> str | None:
        value = project.get(key)
        return str(value) if value is not None else None

    labelled: list[tuple[str, str]] = []
    if version := field_str("version"):
        labelled.append(("Version", version))
    if python := field_str("requires-python"):
        labelled.append(("Python", python))
    if scripts := sorted(project.get("scripts", {})):
        labelled.append(("Entry points", ", ".join(scripts)))

    name = field_str("name") or repo_root.resolve().name
    return ProjectFacts(name=name, description=field_str("description"), labelled=labelled)


def project_dependencies(repo_root: Path) -> list[str]:
    """Return the declared runtime dependencies from pyproject, or an empty list.

    Kept separate from :class:`ProjectFacts` so dependency lines feed the README
    prompt without ever appearing in the CONTEXT.md preamble.

    Args:
        repo_root: The repository root containing pyproject.toml.

    Returns:
        The dependency strings exactly as declared, or empty when absent.
    """
    pyproject = repo_root / "pyproject.toml"
    try:
        project = tomllib.loads(pyproject.read_text()).get("project", {})
    except (tomllib.TOMLDecodeError, OSError):
        return []
    deps = project.get("dependencies", [])
    return [str(d) for d in deps] if isinstance(deps, list) else []


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
