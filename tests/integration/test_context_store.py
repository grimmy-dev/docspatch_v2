"""ScoutCache deep-module behavior tests — real filesystem, no network."""

import gzip
import json
from pathlib import Path

from docspatch.cache import ScoutCache
from docspatch.cache.keys import cache_key
from docspatch.pipelines.scout.planner import build_structured_context
from docspatch.types.source import FileSummary, FunctionMetadata
from docspatch.utils.ignore import ensure_docspatch_ignored


def _cache(tmp_path: Path) -> ScoutCache:
    return ScoutCache(repo_root=tmp_path)


def _summary(path: str, content_hash: str = "abc123") -> FileSummary:
    return FileSummary(path=path, summary="does stuff", content_hash=content_hash)


def test_set_get_round_trip(tmp_path):
    cache = _cache(tmp_path)
    cache.set("src/foo.py", _summary("src/foo.py"))
    result = cache.get("src/foo.py")
    assert result is not None
    assert result.summary == "does stuff"
    assert result.path == "src/foo.py"


def test_get_returns_none_for_missing(tmp_path):
    cache = _cache(tmp_path)
    assert cache.get("src/missing.py") is None


def test_replaces_entry_on_new_write(tmp_path):
    cache = _cache(tmp_path)
    cache.set("src/foo.py", FileSummary(path="src/foo.py", summary="old", content_hash="h1"))
    cache.set("src/foo.py", FileSummary(path="src/foo.py", summary="new", content_hash="h2"))
    result = cache.get("src/foo.py")
    assert result is not None
    assert result.summary == "new"
    assert result.content_hash == "h2"


def test_structured_context_format(tmp_path):
    cache = _cache(tmp_path)
    cache.set(
        "src/mod/foo.py",
        FileSummary(
            path="src/mod/foo.py",
            summary="foo module",
            functions=[FunctionMetadata(name="bar", signature="def bar()")],
        ),
    )
    cache.set(
        "src/mod/baz.py",
        FileSummary(
            path="src/mod/baz.py",
            summary="baz module",
            functions=[FunctionMetadata(name="qux", signature="def qux()")],
        ),
    )
    ctx = build_structured_context(cache, ["src/mod/foo.py", "src/mod/baz.py"])
    assert "src/mod" in ctx
    assert "foo.py" in ctx
    assert "bar" in ctx


def test_gitignore_idempotent(tmp_path):
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("*.pyc\n")

    ensure_docspatch_ignored(tmp_path)
    ensure_docspatch_ignored(tmp_path)

    content = gitignore.read_text()
    assert content.count(".docspatch") == 1


def test_gitignore_creates_if_absent(tmp_path):
    ensure_docspatch_ignored(tmp_path)
    assert (tmp_path / ".gitignore").exists()
    assert ".docspatch" in (tmp_path / ".gitignore").read_text()


def test_cache_info_correct_counts(tmp_path):
    cache = _cache(tmp_path)
    cache.set("a.py", _summary("a.py"))
    cache.set("b.py", _summary("b.py"))

    info = cache.info()
    assert info.file_count == 2
    assert info.total_size_bytes > 0
    assert info.last_build is not None


def test_cache_info_empty_cache(tmp_path):
    cache = _cache(tmp_path)
    info = cache.info()
    assert info.file_count == 0
    assert info.total_size_bytes == 0
    assert info.last_build is None


def test_schema_mismatch_auto_evicts(tmp_path):
    cache = _cache(tmp_path)
    cache_dir = tmp_path / ".docspatch" / "cache" / "scout"
    cache_dir.mkdir(parents=True)

    path = "src/stale.py"
    entry = {
        "_schema_version": 0,
        "path": path,
        "summary": "old",
        "content_hash": "abc",
        "functions": [],
    }
    entry_file = cache_dir / cache_key(path)
    entry_file.write_bytes(gzip.compress(json.dumps(entry).encode()))

    assert cache.get(path) is None
    assert not entry_file.exists()


def test_cache_key_survives_root_relocation(tmp_path):
    """Relative-keyed cache is portable: copying the cache to a new root keeps hits."""
    rel = "src/foo.py"
    cache = _cache(tmp_path)
    cache.set(rel, FileSummary(path=rel, summary="x", content_hash="h"))

    other_root = tmp_path / "moved"
    other_root.mkdir()
    cache_src = tmp_path / ".docspatch" / "cache" / "scout"
    cache_dst = other_root / ".docspatch" / "cache" / "scout"
    cache_dst.mkdir(parents=True)
    for f in cache_src.iterdir():
        (cache_dst / f.name).write_bytes(f.read_bytes())

    cache2 = _cache(other_root)
    hit = cache2.get(rel)
    assert hit is not None
    assert hit.summary == "x"


def test_memoises_within_instance(tmp_path):
    """Repeated get calls do not re-read from disk."""
    cache = _cache(tmp_path)
    cache.set("a.py", _summary("a.py"))

    first = cache.get("a.py")
    for f in (tmp_path / ".docspatch" / "cache" / "scout").iterdir():
        f.unlink()

    second = cache.get("a.py")
    assert first is not None
    assert second is not None
    assert second.summary == first.summary


def test_atomic_write_no_tmp_file_remains(tmp_path):
    from docspatch.utils.fs import atomic_write

    target = tmp_path / "out.txt"
    atomic_write(target, "hello")
    assert target.read_text() == "hello"
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert tmp_files == []
