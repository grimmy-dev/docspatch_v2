"""Commit journal + snapshot helpers."""

from pathlib import Path

from docspatch.pipelines.docs.commit import CommitJournal, read_snapshot, write_snapshot


def test_journal_starts_empty(tmp_path: Path) -> None:
    journal = CommitJournal(tmp_path, "run-1")
    assert journal.committed() == []


def test_journal_records_files_in_order(tmp_path: Path) -> None:
    journal = CommitJournal(tmp_path, "run-1")
    journal.append("pkg/a.py", "hash-a")
    journal.append("pkg/b.py", "hash-b")
    assert journal.committed() == ["pkg/a.py", "pkg/b.py"]


def test_journal_survives_a_fresh_handle(tmp_path: Path) -> None:
    """A new handle on the same run id reads the existing journal — resume relies on this."""
    CommitJournal(tmp_path, "run-1").append("pkg/a.py", "hash-a")
    assert CommitJournal(tmp_path, "run-1").committed() == ["pkg/a.py"]


def test_journal_delete_removes_the_file(tmp_path: Path) -> None:
    journal = CommitJournal(tmp_path, "run-1")
    journal.append("pkg/a.py", "hash-a")
    journal.delete()
    assert journal.committed() == []
    journal.delete()  # idempotent


def test_snapshot_round_trips_nested_paths(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "originals-run-1"
    write_snapshot(snapshot_dir, "pkg/sub/mod.py", "def f():\n    return 1\n")
    assert read_snapshot(snapshot_dir, "pkg/sub/mod.py") == "def f():\n    return 1\n"
