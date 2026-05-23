"""Commit node: write reviewed docstrings to disk transactionally.

Per file: re-check the on-disk hash against the cache, snapshot the original,
insert the docstrings, append to a journal. A failure part-way through
restores every file already written from its snapshot. A clean run deletes
the journal and snapshots; an interrupted run resumes from the journal.
"""

import ast
import gzip
import json
import shutil
import time
from collections import defaultdict
from pathlib import Path

from langgraph.types import interrupt

from docspatch.cache import FileDocState
from docspatch.source import DocstringInsert, file_hash, insert_docstrings, scan_functions
from docspatch.ui import console, status
from docspatch.utils.fs import atomic_write


class CommitJournal:
    """Append-only record of committed files at ``commit-<run_id>.journal``.

    Each line is ``{rel, ts, file_hash_after}``. Survives a hard kill, so a
    resumed run knows which files are already done and can roll the rest back.
    """

    def __init__(self, checkpoint_dir: Path, run_id: str) -> None:
        self.path = checkpoint_dir / f"commit-{run_id}.journal"

    def committed(self) -> list[str]:
        """Repo-relative paths recorded so far, in commit order."""
        if not self.path.exists():
            return []
        rels: list[str] = []
        for line in self.path.read_text().splitlines():
            if line.strip():
                rels.append(json.loads(line)["rel"])
        return rels

    def append(self, rel: str, file_hash_after: str) -> None:
        """Record one committed file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {"rel": rel, "ts": time.time(), "file_hash_after": file_hash_after}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)


def _snapshot_file(snapshot_dir: Path, rel: str) -> Path:
    return snapshot_dir / f"{rel}.gz"


def write_snapshot(snapshot_dir: Path, rel: str, content: str) -> None:
    """Gzip the original file content before it is overwritten."""
    path = _snapshot_file(snapshot_dir, rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(content.encode("utf-8")))


def read_snapshot(snapshot_dir: Path, rel: str) -> str:
    """Read back a snapshotted original."""
    return gzip.decompress(_snapshot_file(snapshot_dir, rel).read_bytes()).decode("utf-8")


def commit_docstrings(ctx, state: dict) -> dict:  # noqa: ANN001 — ctx is GraphContext
    """Write every accepted docstring to disk. The docs graph's commit node.

    Returns ``committed_files`` + ``skipped_files`` on success, or
    ``commit_error`` after rolling back when a write fails mid-sweep.
    """
    accepted = set(state.get("accepted", []))
    entries = [e for e in state.get("entries", []) if f"{e.rel}::{e.qualname}" in accepted]

    by_file: dict[str, list] = defaultdict(list)
    for entry in entries:
        by_file[entry.rel].append(entry)

    checkpoint_dir = ctx.repo_root / ".docspatch" / "checkpoints"
    journal = CommitJournal(checkpoint_dir, ctx.run_id)
    snapshot_dir = checkpoint_dir / f"originals-{ctx.run_id}"
    done = journal.committed()

    committed = list(done)
    skipped: list[str] = []

    with status(f"Writing {len(by_file)} file(s)..."):
        for rel in sorted(by_file):
            if rel in done:
                continue
            path = ctx.repo_root / rel
            source = path.read_text()

            if _conflict(ctx, rel, source):
                action = _resolve_conflict(ctx, rel)
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
                _rollback(ctx, journal, snapshot_dir)
                return {"commit_error": f"{rel}: {exc}"}

            new_hash = file_hash(new_source)
            journal.append(rel, new_hash)
            if ctx.cache is not None:
                # Stat after write so next run fast-skips via size+mtime.
                st = path.stat()
                ctx.cache.set(
                    rel,
                    FileDocState(
                        path=rel,
                        file_hash=new_hash,
                        functions=scan_functions(new_source),
                        size=st.st_size,
                        mtime_ns=st.st_mtime_ns,
                    ),
                )
            committed.append(rel)

    journal.delete()
    shutil.rmtree(snapshot_dir, ignore_errors=True)
    return {"committed_files": committed, "skipped_files": skipped}


def _conflict(ctx, rel: str, source: str) -> bool:  # noqa: ANN001
    """True when the on-disk file no longer matches the hash the cache recorded."""
    if ctx.cache is None:
        return False
    cached = ctx.cache.get(rel)
    return cached is not None and cached.file_hash != file_hash(source)


def _resolve_conflict(ctx, rel: str) -> str:  # noqa: ANN001
    """Ask the user how to handle a concurrently-edited file: skip / force / abort."""
    if not ctx.interactive:
        console.print(f"[yellow]⚠ skipped {rel} — file changed on disk[/yellow]")
        return "skip"
    choice = interrupt({"type": "hash_mismatch", "file": rel})
    return str(choice.get("action", "skip"))


def _rollback(ctx, journal: CommitJournal, snapshot_dir: Path) -> None:  # noqa: ANN001
    """Restore every journalled file from its snapshot, then clear journal + snapshots."""
    for rel in journal.committed():
        atomic_write(ctx.repo_root / rel, read_snapshot(snapshot_dir, rel))
    journal.delete()
    shutil.rmtree(snapshot_dir, ignore_errors=True)
