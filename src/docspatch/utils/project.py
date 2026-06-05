"""Parses pyproject.toml fields, dependencies, and entry point paths."""

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
    """Extract a specific field value from the project table of pyproject.toml.

    Args:
        pyproject_path: Path of the pyproject.toml file.
        field: Configuration key within the project table.

    Returns:
        Field value as a string, or null if missing or invalid.
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
    """Construct a ProjectFacts instance containing core pyproject.toml metadata.

    Args:
        repo_root: Base path of the repository.

    Returns:
        ProjectFacts instance populated with parsed metadata.
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
    """Parse the project table of pyproject.toml into a dictionary.

    Args:
        repo_root: Base path of the repository.

    Returns:
        Parsed project dictionary, or empty if parsing fails.
    """
    try:
        return tomllib.loads((repo_root / "pyproject.toml").read_text()).get("project", {})
    except (tomllib.TOMLDecodeError, OSError):
        return {}


def entry_point_targets(repo_root: Path) -> set[str]:
    """Extract the target module path of all declared entry points in pyproject.toml.

    Args:
        repo_root: Base path of the repository.

    Returns:
        Set of dotted module strings corresponding to entry points.
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
    """Collect and sort all script and gui-script command names declared in pyproject.toml.

    Args:
        repo_root: Base path of the repository.

    Returns:
        Sorted list of declared entry point command names.
    """
    project = _read_project_table(repo_root)
    names = {*project.get("scripts", {}), *project.get("gui-scripts", {})}
    return sorted(names)


def is_entry_point_path(path: str, modules: set[str]) -> bool:
    """Check if a repository-relative path implements one of the entry point modules.

    Args:
        path: Relative path of the source file.
        modules: Set of dotted entry point module names.

    Returns:
        True if the file matches an entry point module pattern.
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
    """Retrieve the raw list of project dependency specifications from pyproject.toml.

    Args:
        repo_root: Base path of the repository.

    Returns:
        List of declared dependency requirements.
    """
    pyproject = repo_root / "pyproject.toml"
    try:
        project = tomllib.loads(pyproject.read_text()).get("project", {})
    except (tomllib.TOMLDecodeError, OSError):
        return []
    deps = project.get("dependencies", [])
    return [str(d) for d in deps] if isinstance(deps, list) else []


def get_dir_tree(root: Path, max_depth: int = 3) -> str:
    """Generate a text representation of the directory structure down to a maximum depth.

    Args:
        root: Starting path to traverse.
        max_depth: Maximum levels of subdirectory expansion.

    Returns:
        Formatted directory tree string.
    """
    lines: list[str] = []
    _walk(root, root, max_depth, 0, lines)
    return "\n".join(lines)


def _walk(root: Path, current: Path, max_depth: int, depth: int, lines: list[str]) -> None:
    """Traverse subdirectories recursively to construct directory tree lines.

    Args:
        root: Root boundary of the tree traversal.
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
            _walk(root, entry, max_depth, depth + 1, lines)
