"""Parsing and selection logic for project-unified summaries."""

import re
from dataclasses import dataclass

from docspatch.pipelines.scout.unified import (
    MARKER_CLOSE,
    MARKER_OPEN,
    PROJECT_CLOSE,
    PROJECT_OPEN,
)

# Derive the open-marker matcher from the writer's template so a format change
# in one place cannot silently break selection here.
_FILE_OPEN_RE = re.compile("^" + re.escape(MARKER_OPEN).replace(re.escape("{path}"), '(?P<path>[^"]*)') + "$")


@dataclass(frozen=True)
class FileBlock:
    """One file's summary, sliced out of CONTEXT.md.

    ``body`` is the inner markdown between the markers; ``path`` is the
    repo-relative source path the block describes.
    """

    path: str
    body: str


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
    buf: list[str] = []
    for line in lines:
        opened = _FILE_OPEN_RE.match(line.strip())
        if opened:
            path, buf = opened.group("path"), []
        elif path is not None and line.strip() == MARKER_CLOSE:
            files.append(FileBlock(path=path, body="\n".join(buf)))
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
