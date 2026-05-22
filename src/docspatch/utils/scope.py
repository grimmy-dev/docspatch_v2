"""Validate + expand CLI path arguments into a concrete ``.py`` file list."""

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
    """Validate ``paths`` and return resolved ``.py`` files.

    Rules per path (fail fast): exists → inside repo → relative → ``.py``
    (files only) → not ignored. Directories walk the filesystem for ``.py``
    files; the ignore filter applies unless ``no_ignore``.

    Returns:
        Deduplicated absolute paths in input order.

    Raises:
        PathError: First failed rule with a specific hint.
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
    """Reject absolute paths; return the repo-relative POSIX string."""
    if raw.is_absolute():
        try:
            rel = raw.resolve().relative_to(root)
        except ValueError as exc:
            raise PathError.outside_repo(str(raw), str(root)) from exc
        raise PathError.absolute_path(str(raw), rel.as_posix())
    return raw.as_posix()


def ensure_exists(raw: Path, abs_path: Path) -> None:
    """Raise ``not_found`` when ``abs_path`` is missing."""
    if not abs_path.exists():
        raise PathError.not_found(str(raw))


def ensure_inside_repo(abs_path: Path, root: Path) -> None:
    """Raise ``outside_repo`` when ``abs_path`` is not under ``root``."""
    try:
        abs_path.relative_to(root)
    except ValueError as exc:
        raise PathError.outside_repo(str(abs_path), str(root)) from exc


def validate_file(rel: str, abs_path: Path, ignore: DocsIgnore, no_ignore: bool) -> None:
    """Apply rules for an explicit file argument."""
    if abs_path.suffix != ".py":
        raise PathError.not_python(rel)
    if not no_ignore and ignore.matches(rel):
        raise PathError.ignored(rel)


def dir_files(rel: str, root: Path, ignore: DocsIgnore, no_ignore: bool) -> list[str]:
    """``.py`` files under ``rel`` (recursive walk), minus ignored ones unless ``no_ignore``."""
    base = root if rel in {".", ""} else root / rel
    found = sorted(p.relative_to(root).as_posix() for p in base.rglob("*.py"))
    return found if no_ignore else ignore.filter(found)
