"""ContextStore deep module behavior tests (Priority 2) — real filesystem, no network."""

import gzip
import json
from pathlib import Path

import pytest

from docspatch.context_store import ContextStore, _cache_key
from docspatch.errors import CacheError
from docspatch.types.source import FileSummary, FunctionMetadata


def _store(tmp_path: Path) -> ContextStore:
    return ContextStore(repo_root=tmp_path)


def _summary(path: str, content_hash: str = "abc123") -> FileSummary:
    return FileSummary(path=path, summary="does stuff", content_hash=content_hash)


def test_context_store_set_get_round_trip(tmp_path):
    store = _store(tmp_path)
    s = _summary("src/foo.py")
    store.set_summary("src/foo.py", s)
    result = store.get_summary("src/foo.py")
    assert result is not None
    assert result.summary == "does stuff"
    assert result.path == "src/foo.py"


def test_context_store_get_returns_none_for_missing(tmp_path):
    store = _store(tmp_path)
    assert store.get_summary("src/missing.py") is None


def test_context_store_replaces_entry_on_new_write(tmp_path):
    store = _store(tmp_path)
    store.set_summary("src/foo.py", FileSummary(path="src/foo.py", summary="old", content_hash="h1"))
    store.set_summary("src/foo.py", FileSummary(path="src/foo.py", summary="new", content_hash="h2"))
    result = store.get_summary("src/foo.py")
    assert result.summary == "new"
    assert result.content_hash == "h2"


def test_context_store_structured_context_format(tmp_path):
    store = _store(tmp_path)
    store.set_summary(
        "src/mod/foo.py",
        FileSummary(
            path="src/mod/foo.py",
            summary="foo module",
            functions=[FunctionMetadata(name="bar", signature="def bar()")],
        ),
    )
    store.set_summary(
        "src/mod/baz.py",
        FileSummary(
            path="src/mod/baz.py",
            summary="baz module",
            functions=[FunctionMetadata(name="qux", signature="def qux()")],
        ),
    )
    ctx = store.get_structured_context(["src/mod/foo.py", "src/mod/baz.py"])
    assert "src/mod" in ctx
    assert "foo.py" in ctx
    assert "bar" in ctx


def test_context_store_gitignore_idempotent(tmp_path):
    store = _store(tmp_path)
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("*.pyc\n")

    store.ensure_gitignore()
    store.ensure_gitignore()  # second call must be no-op

    content = gitignore.read_text()
    assert content.count(".docspatch") == 1


def test_context_store_gitignore_creates_if_absent(tmp_path):
    store = _store(tmp_path)
    store.ensure_gitignore()
    assert (tmp_path / ".gitignore").exists()
    assert ".docspatch" in (tmp_path / ".gitignore").read_text()


def test_cache_info_correct_counts(tmp_path):
    store = _store(tmp_path)
    store.set_summary("a.py", _summary("a.py"))
    store.set_summary("b.py", _summary("b.py"))

    info = store.get_cache_info()
    assert info.file_count == 2
    assert info.total_size_bytes > 0
    assert info.last_build is not None


def test_cache_info_empty_cache(tmp_path):
    store = _store(tmp_path)
    info = store.get_cache_info()
    assert info.file_count == 0
    assert info.total_size_bytes == 0
    assert info.last_build is None


def test_context_store_schema_version_mismatch_raises_cache_error(tmp_path):
    store = _store(tmp_path)
    cache_dir = tmp_path / ".docspatch" / "cache"
    cache_dir.mkdir(parents=True)

    path = "src/stale.py"
    key = _cache_key(path)
    entry = {
        "_schema_version": 0,
        "path": path,
        "summary": "old",
        "content_hash": "abc",
        "functions": [],
    }
    (cache_dir / key).write_bytes(gzip.compress(json.dumps(entry).encode()))

    with pytest.raises(CacheError):
        store.get_summary(path)


def test_atomic_write_no_tmp_file_remains(tmp_path):
    from docspatch.utils.fs import atomic_write

    target = tmp_path / "out.txt"
    atomic_write(target, "hello")
    assert target.read_text() == "hello"
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert tmp_files == []
