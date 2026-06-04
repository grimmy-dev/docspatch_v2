"""Parsing and selection logic for project-unified summaries."""

import re
from dataclasses import dataclass

from docspatch.pipelines.scout.unified import (
    INTERNAL_TIER,
    MARKER_CLOSE,
    MARKER_OPEN,
    PROJECT_CLOSE,
    PROJECT_OPEN,
)

# Derive the open-marker matcher from the writer's template so a format change
# in one place cannot silently break selection here. The trailing ` -->` is
# relaxed to ``(?P<attrs>...)`` so optional marker attributes (e.g. the
# README tier, added later) parse without breaking the path capture.
_FILE_OPEN_RE = re.compile(
    "^"
    + re.escape(MARKER_OPEN)
    .replace(re.escape("{path}"), '(?P<path>[^"]*)')
    .replace(re.escape(" -->"), r'(?P<attrs>[^>]*)-->')
    + "$"
)
_TIER_RE = re.compile(r'tier="(?P<tier>[^"]*)"')

# A block with no tier attribute defaults to public so it is never silently
# dropped; only an explicit internal tag removes a block from the README view.
PUBLIC_TIER = "public"


@dataclass(frozen=True)
class FileBlock:
    """One file's summary, sliced out of CONTEXT.md.

    ``body`` is the inner markdown between the markers; ``path`` is the
    repo-relative source path the block describes; ``tier`` is the README
    relevance tier from the marker (``public`` when none was written).
    """

    path: str
    body: str
    tier: str = PUBLIC_TIER


@dataclass(frozen=True)
class SummaryDoc:
    """A parsed CONTEXT.md: the project preamble plus every per-file block."""

    project: str | None
    files: list[FileBlock]


def parse_summary(text: str) -> SummaryDoc:
    """Split CONTEXT.md into its project preamble and per-file blocks.

    Args:
        text: The full contents of the unified summary file.

    Returns:
        The parsed document; 'project' is null when no preamble is present.
    """
    lines = text.splitlines()
    project = _between(lines, PROJECT_OPEN, PROJECT_CLOSE)
    files: list[FileBlock] = []
    path: str | None = None
    tier = PUBLIC_TIER
    buf: list[str] = []
    for line in lines:
        opened = _FILE_OPEN_RE.match(line.strip())
        if opened:
            path, buf = opened.group("path"), []
            tier_match = _TIER_RE.search(opened.group("attrs"))
            tier = tier_match.group("tier") if tier_match else PUBLIC_TIER
        elif path is not None and line.strip() == MARKER_CLOSE:
            files.append(FileBlock(path=path, body="\n".join(buf), tier=tier))
            path = None
        elif path is not None:
            buf.append(line)
    return SummaryDoc(project=project, files=files)


def _between(lines: list[str], open_marker: str, close_marker: str) -> str | None:
    """Return the inner text between the first matching marker pair, or null.

    Args:
        lines: The document split into lines.
        open_marker: The line that opens the block.
        close_marker: The line that closes it.

    Returns:
        The joined inner lines, or null when the pair is absent.
    """
    try:
        start = lines.index(open_marker)
        end = lines.index(close_marker, start + 1)
    except ValueError:
        return None
    return "\n".join(lines[start + 1 : end])


def under_scope(path: str, scope: str) -> bool:
    """Report whether a file path falls under a directory scope.

    Args:
        path: A repo-relative file path from a marker.
        scope: A repo-relative directory; '.' matches everything.

    Returns:
        True when the file lies inside the scope subtree.
    """
    if scope in {".", "", "./"}:
        return True
    prefix = scope.rstrip("/")
    return path == prefix or path.startswith(prefix + "/")


def select(text: str, scope: str) -> SummaryDoc:
    """Parse CONTEXT.md and keep only the file blocks under 'scope'.

    Args:
        text: The full contents of the unified summary file.
        scope: The repo-relative directory the README covers.

    Returns:
        A document narrowed to the in-scope file blocks.
    """
    doc = parse_summary(text)
    files = [b for b in doc.files if under_scope(b.path, scope)]
    is_root = scope in {".", "", "./"}
    return SummaryDoc(project=doc.project if is_root else None, files=files)


def internal_module_names(text: str, scope: str) -> list[str]:
    """Return the file stems of the in-scope blocks tagged internal.

    These are the modules the README view drops; the quality gate uses them to
    catch any that the model still surfaced as a section heading.

    Args:
        text: The full contents of the unified summary file.
        scope: The repo-relative directory the README covers.

    Returns:
        The internal modules' file stems (e.g. ``pool`` for ``src/db/pool.py``).
    """
    doc = select(text, scope)
    return [b.path.rsplit("/", 1)[-1].removesuffix(".py") for b in doc.files if b.tier == INTERNAL_TIER]


def readme_view(text: str, scope: str) -> SummaryDoc:
    """Select the in-scope blocks a README should be written from.

    Public blocks are kept whole — they already carry their real signatures and
    docstrings, the documented surface a README draws on. ``internal``-tier
    blocks are dropped.

    The ``internal`` tier is a project-level judgment — "would the whole-project
    README mention this?". It is applied only at root scope. When the caller
    scopes the README to a subpackage, that scope is itself the relevance filter:
    the modules under it are the subject, so none are dropped as internal.

    Args:
        text: The full contents of the unified summary file.
        scope: The repo-relative directory the README covers.

    Returns:
        A document narrowed to the README-relevant blocks.
    """
    is_root = scope in {".", "", "./"}
    doc = select(text, scope)
    files = [b for b in doc.files if not (is_root and b.tier == INTERNAL_TIER)]
    return SummaryDoc(project=doc.project, files=files)
