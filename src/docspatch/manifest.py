"""Content-hash change manifest: one baseline record per pipeline, diffed each
run to learn what changed. Pipelines own disjoint records in one shared file."""

import gzip
import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from docspatch.source import compress, file_hash
from docspatch.utils.errors import CacheError
from docspatch.utils.fs import atomic_write

MANIFEST_NAME = "manifest.json.gz"
"""Single per-repo manifest file, under ``.docspatch``."""


def semantic_hash(source: str) -> str:
    """Hash source ignoring formatting, comments, and docstrings.

    ``compress`` strips docstrings, comments, and blank lines and normalizes
    indentation, so a docstring-only edit (what ``dp docs`` writes) leaves the
    hash unchanged and never flags a README stale.

    Args:
        source: Raw Python source text.

    Returns:
        The hexadecimal semantic hash.
    """
    return file_hash(compress(source))


@dataclass(frozen=True)
class ChangeSet:
    """What changed for one pipeline since its baseline.

    ``removed`` carries paths present in the baseline but gone from the working
    tree; the files no longer exist, so only their paths survive.
    """

    added: list[str]
    updated: list[str]
    removed: list[str]

    @property
    def changed(self) -> list[str]:
        """Paths the pipeline should treat as stale (added plus updated).

        Returns:
            The union of added and updated paths.
        """
        return [*self.added, *self.updated]

    @property
    def empty(self) -> bool:
        """Whether nothing changed at all.

        Returns:
            True when no path was added, updated, or removed.
        """
        return not (self.added or self.updated or self.removed)


class ChangeManifest:
    """Per-pipeline content-hash baselines stored in one gzipped-JSON file.

    Each pipeline owns a disjoint record keyed by name. A record is replaced
    wholesale on that pipeline's success — no append, no history, no GC.
    """

    def __init__(self, repo_root: Path) -> None:
        """Bind the manifest to a repository's ``.docspatch`` directory.

        Args:
            repo_root: The repository root.
        """
        self.path = repo_root.resolve() / ".docspatch" / MANIFEST_NAME

    def baseline(self, pipeline: str) -> dict[str, str] | None:
        """Return a pipeline's stored hashes, or null when it never succeeded.

        Args:
            pipeline: The pipeline's record key (e.g. ``"readme"``).

        Returns:
            The stored ``path -> hash`` map, or null on a first-ever run.
        """
        record = self._load().get(pipeline)
        if record is None:
            return None
        hashes = record.get("hashes", {})
        return {str(k): str(v) for k, v in hashes.items()}

    def stamps(self, pipeline: str) -> dict[str, tuple[int, int]]:
        """Return stored ``path -> (size, mtime_ns)`` for fast-skip hashing.

        These let a run reuse a stored hash for an unchanged file instead of
        re-reading and re-compressing it. Empty when the pipeline never stored
        stamps, which simply forces a recompute.

        Args:
            pipeline: The pipeline's record key.

        Returns:
            The stored stat map, empty when absent.
        """
        record = self._load().get(pipeline) or {}
        stamps = record.get("stamps", {})
        return {str(k): (int(v[0]), int(v[1])) for k, v in stamps.items() if len(v) == 2}

    def diff(self, pipeline: str, current: dict[str, str]) -> ChangeSet:
        """Classify current hashes against a pipeline's baseline.

        A first-ever run (no baseline) treats every current path as added.

        Args:
            pipeline: The pipeline's record key.
            current: The freshly computed ``path -> semantic_hash`` map.

        Returns:
            The added, updated, and removed paths.
        """
        baseline = self.baseline(pipeline) or {}
        added = [p for p in current if p not in baseline]
        updated = [p for p in current if p in baseline and current[p] != baseline[p]]
        removed = [p for p in baseline if p not in current]
        return ChangeSet(added=sorted(added), updated=sorted(updated), removed=sorted(removed))

    def commit(self, pipeline: str, current: dict[str, str], stamps: dict[str, tuple[int, int]] | None = None) -> None:
        """Replace a pipeline's baseline with the current hashes and a fresh stamp.

        Called only on accept/write, so a cancelled run leaves the baseline
        untouched and the next run re-detects the same changes. ``stamps`` are
        stored alongside so the next run can fast-skip unchanged files.

        Args:
            pipeline: The pipeline's record key.
            current: The ``path -> semantic_hash`` map to store as the new baseline.
            stamps: Optional ``path -> (size, mtime_ns)`` for fast-skip hashing.

        Raises:
            CacheError: Writing the manifest fails.
        """
        data = self._load()
        record: dict = {"uuid": uuid.uuid4().hex, "hashes": dict(current)}
        if stamps:
            record["stamps"] = {p: [size, mtime] for p, (size, mtime) in stamps.items()}
        data[pipeline] = record
        try:
            atomic_write(self.path, gzip.compress(json.dumps(data).encode()))
        except OSError as exc:
            raise CacheError.write_failed(str(self.path), exc) from exc

    def _load(self) -> dict[str, dict]:
        """Read every pipeline record, treating any corruption as absent.

        Returns:
            The full ``pipeline -> record`` map, empty when the file is missing
            or unreadable.
        """
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return {}
        except OSError as exc:
            raise CacheError.read_failed(str(self.path), exc) from exc
        try:
            data = json.loads(gzip.decompress(raw))
        except (OSError, EOFError, ValueError) as exc:
            # A corrupt manifest must not wedge the pipeline — drop it and treat
            # every pipeline as a first-ever run, rebuilt on the next success.
            self.path.unlink(missing_ok=True)
            _ = exc
            return {}
        return data if isinstance(data, dict) else {}
