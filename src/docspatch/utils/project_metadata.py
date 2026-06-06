"""Reads project name, description, version, and dependencies from pyproject.toml."""

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


def read_project_table(repo_root: Path) -> dict:
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


def get_pyproject_field(repo_root: Path, field: str) -> str | None:
    """Extract a specific field value from the project table of pyproject.toml.

    Args:
        repo_root: Base path of the repository.
        field: Configuration key within the project table.

    Returns:
        Field value as a string, or null if missing or invalid.
    """
    value = read_project_table(repo_root).get(field)
    return str(value) if value is not None else None


def project_facts(repo_root: Path) -> ProjectFacts:
    """Construct a ProjectFacts instance containing core pyproject.toml metadata.

    Args:
        repo_root: Base path of the repository.

    Returns:
        ProjectFacts instance populated with parsed metadata.
    """
    project = read_project_table(repo_root)

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
    """Retrieve the raw list of project dependency specifications from pyproject.toml.

    Args:
        repo_root: Base path of the repository.

    Returns:
        List of declared dependency requirements.
    """
    deps = read_project_table(repo_root).get("dependencies", [])
    return [str(d) for d in deps] if isinstance(deps, list) else []
