"""Resolves paths, validates repository boundaries, and finds Python source files."""

from pathlib import Path

from docspatch.utils.errors import PathError
from docspatch.utils.ignore import DocsIgnore


def discover_targets(
    paths: list[Path],
    repo_root: Path,
    ignore: DocsIgnore,
    *,
    no_ignore: bool = False,
) -> list[Path]:
    """Resolve and validate input paths into a list of absolute Python source files.

    Args:
        paths: List of paths to search or evaluate.
        repo_root: Base path of the repository.
        ignore: Configured ignore pattern spec.
        no_ignore: Flag to disable ignore filters.

    Returns:
        List of validated absolute Python file paths.

    Raises:
        PathError: Paths are empty, files are invalid, or outside repository boundaries.
    """
    if not paths:
        raise PathError.not_found("(no paths)")

    root = repo_root.resolve()
    seen: dict[Path, None] = {}

    for raw in paths:
        rel = ensure_relative(raw, root)
        abs_path = (root / rel).resolve()
        ensure_exists(raw, abs_path)
        ensure_inside_repo(abs_path, root)
        if abs_path.is_dir():
            for found_rel in dir_files(rel, root, ignore, no_ignore):
                seen.setdefault((root / found_rel).resolve(), None)
            continue
        validate_file(rel, abs_path, ignore, no_ignore)
        seen.setdefault(abs_path, None)

    if not seen:
        raise PathError.not_python(str(paths[0]))
    return list(seen)


def ensure_relative(raw: Path, root: Path) -> str:
    """Verify that a path is relative to the repository, raising an error if absolute.

    Args:
        raw: Path to evaluate.
        root: Base repository directory.

    Returns:
        Relative POSIX string.

    Raises:
        PathError: The path is absolute or falls outside the repository tree.
    """
    if raw.is_absolute():
        try:
            rel = raw.resolve().relative_to(root)
        except ValueError as exc:
            raise PathError.outside_repo(str(raw), str(root)) from exc
        raise PathError.absolute_path(str(raw), rel.as_posix())
    return raw.as_posix()


def ensure_exists(raw: Path, abs_path: Path) -> None:
    """Verify that an absolute path exists on the filesystem.

    Args:
        raw: User-provided input path.
        abs_path: Resolved absolute path.

    Raises:
        PathError: The target file or directory does not exist.
    """
    if not abs_path.exists():
        raise PathError.not_found(str(raw))


def ensure_inside_repo(abs_path: Path, root: Path) -> None:
    """Confirm that an absolute path lies within the repository directory structure.

    Args:
        abs_path: Resolved absolute path to evaluate.
        root: Repository base directory.

    Raises:
        PathError: The resolved path is not located within the repository boundary.
    """
    try:
        abs_path.relative_to(root)
    except ValueError as exc:
        raise PathError.outside_repo(str(abs_path), str(root)) from exc


def validate_file(rel: str, abs_path: Path, ignore: DocsIgnore, no_ignore: bool) -> None:
    """Verify that a file has a .py extension and is not excluded by ignore filters.

    Args:
        rel: Relative file path.
        abs_path: Absolute file path.
        ignore: Ignore pattern instance.
        no_ignore: Flag to disable ignore filters.

    Raises:
        PathError: The path does not end with .py or is ignored.
    """
    if abs_path.suffix != ".py":
        raise PathError.not_python(rel)
    if not no_ignore and ignore.matches(rel):
        raise PathError.ignored(rel)


def dir_files(rel: str, root: Path, ignore: DocsIgnore, no_ignore: bool) -> list[str]:
    """List all non-ignored Python source files under a directory recursively.

    Args:
        rel: Relative path to evaluate.
        root: Base repository directory.
        ignore: Ignore pattern matcher.
        no_ignore: Flag to bypass ignore checks.

    Returns:
        List of relative paths to discovered python files.
    """
    base = root if rel in {".", ""} else root / rel
    found = sorted(p.relative_to(root).as_posix() for p in base.rglob("*.py"))
    return found if no_ignore else ignore.filter(found)
