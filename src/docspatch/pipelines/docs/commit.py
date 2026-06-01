"""Implement the commit phase to apply docstring updates to repository source files."""

import ast
import gzip
import json
import shutil
import time
from collections import defaultdict
from pathlib import Path

from langgraph.types import interrupt

from docspatch.cache import FileDocState
from docspatch.schemas import FunctionDocState
from docspatch.source import (
    MODULE_QUALNAME,
    DocstringInsert,
    file_hash,
    insert_docstrings,
    scan_functions,
)
from docspatch.ui import console, status
from docspatch.utils.fs import atomic_write


class CommitJournal:
    """Append-only record of committed files at ``commit-<run_id>.journal``.

    Each line is ``{rel, ts, file_hash_after}``. Survives a hard kill, so a
    resumed run knows which files are already done and can roll the rest back.
    """

    def __init__(self, checkpoint_dir: Path, run_id: str) -> None:
        """Initialize the commit journal with checkpoint directory and run identifier.

        Args:
            checkpoint_dir: The directory used for storing run state.
            run_id: A unique identifier for the current batch process.
        """
        self.path = checkpoint_dir / f"commit-{run_id}.journal"
        # Load once; mutate on append. Membership is O(1) and rollback keeps order.
        self._order: list[str] = _read_journal(self.path)
        self._set: set[str] = set(self._order)

    def committed_order(self) -> list[str]:
        """Retrieve the repository-relative paths recorded so far, in commit order.

        Returns:
            The list of committed paths.
        """
        return list(self._order)

    def is_committed(self, rel: str) -> bool:
        """Determine if a file has already been journalled in the current run.

        Args:
            rel: The relative file path.

        Returns:
            True if the file is committed.
        """
        return rel in self._set

    def append(self, rel: str, file_hash_after: str) -> None:
        """Record a single committed file to the journal.

        Args:
            rel: The relative file path.
            file_hash_after: The hash of the file after document insertion.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {"rel": rel, "ts": time.time(), "file_hash_after": file_hash_after}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        self._order.append(rel)
        self._set.add(rel)

    def delete(self) -> None:
        """Remove the current journal file from the file system."""
        self.path.unlink(missing_ok=True)
        self._order.clear()
        self._set.clear()


def _read_journal(path: Path) -> list[str]:
    """Load the list of committed file paths from an existing journal file.

    Args:
        path: The file system path to the journal.

    Returns:
        A list of paths in order.
    """
    if not path.exists():
        return []
    rels: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rels.append(json.loads(line)["rel"])
        except json.JSONDecodeError, KeyError, TypeError:
            continue
    return rels


def _snapshot_file(snapshot_dir: Path, rel: str) -> Path:
    """Construct the path for a gzipped snapshot file.

    Args:
        snapshot_dir: The directory containing snapshots.
        rel: The relative path identifier.

    Returns:
        The Path object to the snapshot.
    """
    return snapshot_dir / f"{rel}.gz"


def write_snapshot(snapshot_dir: Path, rel: str, content: str) -> None:
    """Gzip and save the original file content before it is overwritten."""
    path = _snapshot_file(snapshot_dir, rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(content.encode("utf-8")))


def read_snapshot(snapshot_dir: Path, rel: str) -> str:
    """Decompress and return the original file content from a snapshot.

    Returns:
        The original file text.
    """
    return gzip.decompress(_snapshot_file(snapshot_dir, rel).read_bytes()).decode("utf-8")


def commit_docstrings(ctx, state: dict) -> dict:  # noqa: ANN001 — ctx is GraphContext
    """Apply accepted docstrings to the repository source files.

    Returns:
        A dictionary reporting committed files, skipped files, or errors.

    Raises:
        Exception: An error occurs during file writing, triggering a rollback.
    """
    accepted = set(state.get("accepted", []))
    entries = [e for e in state.get("entries", []) if f"{e.rel}::{e.qualname}" in accepted]

    by_file: dict[str, list] = defaultdict(list)
    for entry in entries:
        by_file[entry.rel].append(entry)

    checkpoint_dir = ctx.repo_root / ".docspatch" / "checkpoints"
    journal = CommitJournal(checkpoint_dir, ctx.run_id)
    snapshot_dir = checkpoint_dir / f"originals-{ctx.run_id}"

    committed = journal.committed_order()
    skipped: list[str] = []
    # Remember the pre-commit cache entry for every file we mutate so a rollback
    # can restore it. Without this, _rollback restores disk to original content
    # while the cache still points at the post-insert hash, and the next run
    # mis-detects every rolled-back file as edited on disk.
    cache_snapshots: dict[str, FileDocState | None] = {}

    with status(f"Writing {len(by_file)} file(s)..."):
        for rel in sorted(by_file):
            if journal.is_committed(rel):
                continue
            path = ctx.repo_root / rel
            source = path.read_text()

            if _conflict(ctx, rel, source):
                action = _resolve_conflict(ctx, rel)
                if action == "abort":
                    _rollback(ctx, journal, snapshot_dir, cache_snapshots)
                    return {"commit_error": f"commit aborted at {rel} — file changed on disk"}
                if action == "skip":
                    skipped.append(rel)
                    continue

            try:
                ast.parse(source)
            except SyntaxError:
                console.print(f"[yellow]⚠ skipped {rel} — file no longer parses[/yellow]")
                skipped.append(rel)
                continue

            inserts = [DocstringInsert(qualname=e.qualname, docstring=e.docstring) for e in by_file[rel]]
            try:
                new_source = insert_docstrings(source, items=inserts)
                write_snapshot(snapshot_dir, rel, source)
                atomic_write(path, new_source)
            except Exception as exc:  # noqa: BLE001 — any write failure rolls the sweep back
                _rollback(ctx, journal, snapshot_dir, cache_snapshots)
                return {"commit_error": f"{rel}: {exc}"}

            new_hash = file_hash(new_source)
            journal.append(rel, new_hash)
            if ctx.cache is not None:
                # Stat after write so next run fast-skips via size+mtime.
                st = path.stat()
                prior = ctx.cache.get(rel)
                cache_snapshots[rel] = prior
                ctx.cache.set(
                    rel,
                    FileDocState(
                        path=rel,
                        file_hash=new_hash,
                        functions=_functions_after_insert(prior, inserts, new_source),
                        size=st.st_size,
                        mtime_ns=st.st_mtime_ns,
                    ),
                )
            committed.append(rel)

    journal.delete()
    shutil.rmtree(snapshot_dir, ignore_errors=True)
    return {"committed_files": committed, "skipped_files": skipped}


def _conflict(ctx, rel: str, source: str) -> bool:  # noqa: ANN001
    """Detect if the on-disk file content differs from the recorded cache hash.

    Returns:
        True if a conflict exists.
    """
    if ctx.cache is None:
        return False
    cached = ctx.cache.get(rel)
    return cached is not None and cached.file_hash != file_hash(source)


def _resolve_conflict(ctx, rel: str) -> str:  # noqa: ANN001
    """Determine the resolution action for a concurrently modified file.

    Returns:
        The selected resolution action as a string.
    """
    if not ctx.interactive:
        console.print(f"[yellow]⚠ skipped {rel} — file changed on disk[/yellow]")
        return "skip"
    choice = interrupt({"type": "hash_mismatch", "file": rel})
    return str(choice.get("action", "skip"))


def _rollback(  # noqa: ANN001
    ctx,
    journal: CommitJournal,
    snapshot_dir: Path,
    cache_snapshots: dict[str, FileDocState | None],
) -> None:
    """Restore files and cache entries to the state prior to the current commit sweep."""
    for rel in journal.committed_order():
        atomic_write(ctx.repo_root / rel, read_snapshot(snapshot_dir, rel))
        if ctx.cache is not None and rel in cache_snapshots:
            prior = cache_snapshots[rel]
            if prior is None:
                ctx.cache.delete(rel)
            else:
                ctx.cache.set(rel, prior)
    journal.delete()
    shutil.rmtree(snapshot_dir, ignore_errors=True)


def _functions_after_insert(
    prior: FileDocState | None,
    inserts: list[DocstringInsert],
    new_source: str,
) -> dict[str, FunctionDocState]:
    """Calculate function states following docstring insertions.

    Returns:
        A dictionary mapping qualnames to FunctionDocState.
    """
    if prior is None:
        return scan_functions(new_source)
    functions = dict(prior.functions)
    for ins in inserts:
        if ins.qualname == MODULE_QUALNAME:
            continue
        cached = functions.get(ins.qualname)
        if cached is None:
            return scan_functions(new_source)
        functions[ins.qualname] = FunctionDocState(
            hash=cached.hash,
            has_docstring=True,
            line_start=cached.line_start,
        )
    return functions
