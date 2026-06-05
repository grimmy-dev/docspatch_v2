"""Content-hash change manifest: one baseline record per pipeline, diffed each
run to detect changes. Pipelines own disjoint records in one shared file."""

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
    """Generate a file hash from a compressed source string that has comments and docstrings stripped.

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
        """Collect the list of all added and updated file paths.

        Returns:
            The union of added and updated paths.
        """
        return [*self.added, *self.updated]

    @property
    def empty(self) -> bool:
        """Verify if there are absolutely no added, updated, or removed file paths in this set.

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
        """Resolve the filepath of the gzipped JSON manifest relative to the repository root.

        Args:
            repo_root: The repository root.
        """
        self.path = repo_root.resolve() / ".docspatch" / MANIFEST_NAME

    def baseline(self, pipeline: str) -> dict[str, str] | None:
        """Retrieve the mapped baseline hashes from the last successful run of a specific pipeline.

        Args:
            pipeline: The pipeline's record key (e.g. "readme").

        Returns:
            The stored path-to-hash map, or null on a first-ever run.
        """
        record = self._load().get(pipeline)
        if record is None:
            return None
        hashes = record.get("hashes", {})
        return {str(k): str(v) for k, v in hashes.items()}

    def stamps(self, pipeline: str) -> dict[str, tuple[int, int]]:
        """Load cached file sizes and modification times for skipping redundant hashing.

        Args:
            pipeline: The pipeline's record key.

        Returns:
            The stored stat map, empty when absent.
        """
        record = self._load().get(pipeline) or {}
        stamps = record.get("stamps", {})
        return {str(k): (int(v[0]), int(v[1])) for k, v in stamps.items() if len(v) == 2}

    def compute_state(self, pipeline: str, root: Path, paths: list[str]) -> tuple[dict[str, str], dict[str, tuple[int, int]]]:
        """Generate current semantic hashes and stat stamps for a list of repository files.

        Args:
            pipeline: The pipeline's record key.
            root: The repository root the paths are relative to.
            paths: Repo-relative file paths to hash.

        Returns:
            The path-to-semantic_hash and path-to-(size, mtime_ns) maps.
        """
        prev_hashes = self.baseline(pipeline) or {}
        prev_stamps = self.stamps(pipeline)
        hashes: dict[str, str] = {}
        stamps: dict[str, tuple[int, int]] = {}
        for p in paths:
            st = (root / p).stat()
            stamp = (st.st_size, st.st_mtime_ns)
            cached = prev_hashes.get(p)
            if cached is not None and prev_stamps.get(p) == stamp:
                hashes[p] = cached
            else:
                hashes[p] = semantic_hash((root / p).read_text(encoding="utf-8"))
            stamps[p] = stamp
        return hashes, stamps

    def diff(self, pipeline: str, current: dict[str, str]) -> ChangeSet:
        """Compare current hashes against baseline records to categorize additions, modifications, and deletions.

        Args:
            pipeline: The pipeline's record key.
            current: The freshly computed path-to-semantic_hash map.

        Returns:
            The added, updated, and removed paths.
        """
        baseline = self.baseline(pipeline) or {}
        added = [p for p in current if p not in baseline]
        updated = [p for p in current if p in baseline and current[p] != baseline[p]]
        removed = [p for p in baseline if p not in current]
        return ChangeSet(added=sorted(added), updated=sorted(updated), removed=sorted(removed))

    def commit(self, pipeline: str, current: dict[str, str], stamps: dict[str, tuple[int, int]] | None = None) -> None:
        """Save the updated hashes and file system stamps atomically into the compressed manifest.

        Args:
            pipeline: The pipeline's record key.
            current: The path-to-semantic_hash map to store as the new baseline.
            stamps: Optional path-to-(size, mtime_ns) for fast-skip hashing.

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
        """Read and decompress the manifest file from disk, returning empty data if it is missing or corrupted.

        Returns:
            The full pipeline-to-record map, empty when the file is missing or unreadable.

        Raises:
            CacheError: Reading the manifest fails due to OSError.
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
