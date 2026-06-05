"""Apply accepted docstrings to source files, journalling writes with snapshots
for rollback and detecting files changed on disk since planning."""

import ast
import gzip
import json
import shutil
import time
from collections import defaultdict
from pathlib import Path

from langgraph.types import interrupt

from docspatch.source import (
    DocstringInsert,
    file_hash,
    insert_docstrings,
)
from docspatch.ui import console, status
from docspatch.utils.fs import atomic_write
from docspatch.utils.logging import get_logger

log = get_logger("docs.commit")


class CommitJournal:
    """Append-only record of committed files at ``commit-<run_id>.journal``.

    Each line is ``{rel, ts, file_hash_after}``. Survives a hard kill, so a
    resumed run knows which files are already done and can roll the rest back.
    """

    def __init__(self, checkpoint_dir: Path, run_id: str) -> None:
        """Construct a commit journal tracking file system updates under the checkpoint directory.

        Args:
            checkpoint_dir: The directory used for storing run state.
            run_id: A unique identifier for the current batch process.
        """
        self.path = checkpoint_dir / f"commit-{run_id}.journal"
        # Load once; mutate on append. Membership is O(1) and rollback keeps order.
        self._order: list[str] = _read_journal(self.path)
        self._set: set[str] = set(self._order)

    def committed_order(self) -> list[str]:
        """Return the ordered sequence of file paths committed during the current run.

        Returns:
            The list of committed paths.
        """
        return list(self._order)

    def is_committed(self, rel: str) -> bool:
        """Determine whether a specific file has already been journaled as committed.

        Args:
            rel: The relative file path.

        Returns:
            True if the file is committed.
        """
        return rel in self._set

    def append(self, rel: str, file_hash_after: str) -> None:
        """Write a new file commit record containing its post-write hash into the journal file.

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
        """Unlink the journal file on disk and clear all cached tracking sequences."""
        self.path.unlink(missing_ok=True)
        self._order.clear()
        self._set.clear()


def _read_journal(path: Path) -> list[str]:
    """Load and parse a line-delimited JSON journal file to construct the sequence of committed paths.

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
    """Resolve the gzipped snapshot path corresponding to a relative file identifier.

    Args:
        snapshot_dir: The directory containing snapshots.
        rel: The relative path identifier.

    Returns:
        The Path object to the snapshot.
    """
    return snapshot_dir / f"{rel}.gz"


def write_snapshot(snapshot_dir: Path, rel: str, content: str) -> None:
    """Compress and save the current source file content into a backup snapshot.

    Args:
        snapshot_dir: The directory to write the snapshot to.
        rel: The relative file path identifier.
        content: The raw file content to store.
    """
    path = _snapshot_file(snapshot_dir, rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(content.encode("utf-8")))


def read_snapshot(snapshot_dir: Path, rel: str) -> str:
    """Decompress and load the original source text from a backup snapshot.

    Args:
        snapshot_dir: The directory holding snapshots.
        rel: The relative file path identifier.

    Returns:
        The original file text.
    """
    return gzip.decompress(_snapshot_file(snapshot_dir, rel).read_bytes()).decode("utf-8")


def commit_docstrings(ctx, state: dict) -> dict:  # noqa: ANN001 — ctx is GraphContext
    """Apply accepted docstrings to physical files while executing safety checks and rollback routines.

    Args:
        ctx: The GraphContext object.
        state: The review workflow state dictionary.

    Returns:
        A dictionary reporting committed files, skipped files, or errors.
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
    log.debug("commit start: %d file(s), %d accepted entry(ies), %d already journalled", len(by_file), len(entries), len(committed))

    with status(f"Writing {len(by_file)} file(s)..."):
        for rel in sorted(by_file):
            if journal.is_committed(rel):
                log.debug("skip %s — already committed this run", rel)
                continue
            path = ctx.repo_root / rel
            source = path.read_text()

            if _conflict(ctx, rel, source):
                action = _resolve_conflict(ctx, rel)
                log.debug("conflict on %s — resolved as %s", rel, action)
                if action == "abort":
                    _rollback(ctx, journal, snapshot_dir)
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
                log.debug("write failed on %s: %s — rolling back %d file(s)", rel, exc, len(journal.committed_order()))
                _rollback(ctx, journal, snapshot_dir)
                return {"commit_error": f"{rel}: {exc}"}

            journal.append(rel, file_hash(new_source))
            committed.append(rel)
            log.debug("wrote %s (%d docstring(s))", rel, len(inserts))

    journal.delete()
    shutil.rmtree(snapshot_dir, ignore_errors=True)
    log.debug("commit done: %d written, %d skipped", len(committed), len(skipped))
    return {"committed_files": committed, "skipped_files": skipped}


def _conflict(ctx, rel: str, source: str) -> bool:  # noqa: ANN001
    """Verify if the current file content on disk differs from its plan-time hash.

    Args:
        ctx: The GraphContext containing planned hashes.
        rel: The relative path of the file.
        source: The current source text of the file on disk.

    Returns:
        True when the current source differs from the plan-time hash.
    """
    planned = ctx.plan_hashes.get(rel)
    return planned is not None and planned != file_hash(source)


def _resolve_conflict(ctx, rel: str) -> str:  # noqa: ANN001
    """Prompt the user or default to skipping when a file modification conflict is found.

    Args:
        ctx: The GraphContext containing execution parameters.
        rel: The relative path of the conflicting file.

    Returns:
        The selected resolution action as a string.
    """
    if not ctx.interactive:
        console.print(f"[yellow]⚠ skipped {rel} — file changed on disk[/yellow]")
        return "skip"
    choice = interrupt({"type": "hash_mismatch", "file": rel})
    return str(choice.get("action", "skip"))


def _rollback(ctx, journal: CommitJournal, snapshot_dir: Path) -> None:  # noqa: ANN001
    """Revert all modified source files tracked in the journal using backup snapshots.

    Args:
        ctx: The GraphContext of the run.
        journal: The CommitJournal instance tracking commits.
        snapshot_dir: The directory containing backup snapshots.
    """
    for rel in journal.committed_order():
        atomic_write(ctx.repo_root / rel, read_snapshot(snapshot_dir, rel))
    journal.delete()
    shutil.rmtree(snapshot_dir, ignore_errors=True)
