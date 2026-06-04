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


def _read_project_table(repo_root: Path) -> dict:
    """Return the ``[project]`` table from pyproject, or empty on any error.

    Returns:
        The parsed project table, empty when the file is missing or malformed.
    """
    try:
        return tomllib.loads((repo_root / "pyproject.toml").read_text()).get("project", {})
    except (tomllib.TOMLDecodeError, OSError):
        return {}


def entry_point_targets(repo_root: Path) -> set[str]:
    """Return the dotted module of every declared entry point.

    Covers ``[project.scripts]``, ``[project.gui-scripts]``, and every
    ``[project.entry-points.*]`` group. The module is the part before ``:`` in a
    ``module:attr`` object reference; these modules are always README-relevant
    (the S1 deterministic floor behind the missing-command guarantee).

    Args:
        repo_root: The repository root containing pyproject.toml.

    Returns:
        The set of dotted module names, empty when no entry points are declared.
    """
    project = _read_project_table(repo_root)
    refs: list[str] = []
    refs += list(project.get("scripts", {}).values())
    refs += list(project.get("gui-scripts", {}).values())
    for group in project.get("entry-points", {}).values():
        if isinstance(group, dict):
            refs += list(group.values())
    return {ref.split(":", 1)[0].strip() for ref in refs if isinstance(ref, str) and ref}


def entry_point_commands(repo_root: Path) -> list[str]:
    """Return the names of every declared console/GUI script, sorted.

    These are the commands a user types — the README is expected to document
    them. A project that declares none (a library, a web service started by a
    framework runner) yields an empty list, which makes the coverage gate a
    no-op rather than a false failure.

    Args:
        repo_root: The repository root containing pyproject.toml.

    Returns:
        The sorted script names, empty when none are declared.
    """
    project = _read_project_table(repo_root)
    names = {*project.get("scripts", {}), *project.get("gui-scripts", {})}
    return sorted(names)


def is_entry_point_path(path: str, modules: set[str]) -> bool:
    """Report whether a repo-relative path implements one of the entry-point modules.

    A dotted module ``pkg.cli`` matches the file ``…/pkg/cli.py`` or the package
    ``…/pkg/cli/__init__.py``, regardless of a ``src/`` prefix — the match is on
    the path suffix so any src-layout resolves.

    Args:
        path: A repo-relative source path from a summary.
        modules: Dotted entry-point modules from :func:`entry_point_targets`.

    Returns:
        True when the path is the target of a declared entry point.
    """
    rel = path.replace("\\", "/")
    for module in modules:
        stem = module.replace(".", "/")
        if rel == f"{stem}.py" or rel.endswith(f"/{stem}.py"):
            return True
        if rel == f"{stem}/__init__.py" or rel.endswith(f"/{stem}/__init__.py"):
            return True
    return False


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
