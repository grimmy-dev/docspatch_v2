"""Discovers entry-point commands and modules declared in pyproject.toml."""

from pathlib import Path

from docspatch.utils.project_metadata import read_project_table


def entry_point_targets(repo_root: Path) -> set[str]:
    """Extract the target module path of all declared entry points in pyproject.toml.

    Args:
        repo_root: Base path of the repository.

    Returns:
        Set of dotted module strings corresponding to entry points.
    """
    project = read_project_table(repo_root)
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
    project = read_project_table(repo_root)
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
