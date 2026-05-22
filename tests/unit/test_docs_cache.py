"""DocsCache: per-file gzip-JSON state, schema-versioned, hash-based invalidation."""

import gzip
from pathlib import Path

from docspatch.cache import DocsCache, FileDocState, FunctionDocState


def make_state(file_hash: str = "deadbeef") -> FileDocState:
    return FileDocState(
        path="src/foo.py",
        file_hash=file_hash,
        functions={
            "add": FunctionDocState(hash="aaa", has_docstring=True, line_start=10),
            "Foo.bar": FunctionDocState(hash="bbb", has_docstring=False, line_start=20),
        },
    )


def test_get_missing_path_returns_none(tmp_path: Path) -> None:
    cache = DocsCache(tmp_path)
    assert cache.get_state("src/missing.py") is None


def test_round_trip_set_then_get(tmp_path: Path) -> None:
    cache = DocsCache(tmp_path)
    state = make_state()

    cache.set_state("src/foo.py", state)

    loaded = cache.get_state("src/foo.py")
    assert loaded == state


def test_round_trip_survives_new_instance(tmp_path: Path) -> None:
    cache = DocsCache(tmp_path)
    cache.set_state("src/foo.py", make_state())

    fresh = DocsCache(tmp_path)
    assert fresh.get_state("src/foo.py") == make_state()


def test_needs_rerun_empty_cache_returns_all_targets(tmp_path: Path) -> None:
    cache = DocsCache(tmp_path)
    current = {
        "add": FunctionDocState(hash="aaa", has_docstring=False),
        "Foo.bar": FunctionDocState(hash="bbb", has_docstring=False),
    }
    assert sorted(cache.needs_rerun("src/foo.py", current)) == ["Foo.bar", "add"]


def test_needs_rerun_skips_cached_documented(tmp_path: Path) -> None:
    cache = DocsCache(tmp_path)
    cache.set_state(
        "src/foo.py",
        FileDocState(
            path="src/foo.py",
            file_hash="h",
            functions={"add": FunctionDocState(hash="aaa", has_docstring=True)},
        ),
    )
    current = {"add": FunctionDocState(hash="aaa", has_docstring=True)}
    assert cache.needs_rerun("src/foo.py", current) == []


def test_needs_rerun_targets_changed_hash(tmp_path: Path) -> None:
    cache = DocsCache(tmp_path)
    cache.set_state(
        "src/foo.py",
        FileDocState(
            path="src/foo.py",
            file_hash="h",
            functions={"add": FunctionDocState(hash="aaa", has_docstring=True)},
        ),
    )
    current = {"add": FunctionDocState(hash="bbb", has_docstring=False)}
    assert cache.needs_rerun("src/foo.py", current) == ["add"]


def test_needs_rerun_targets_missing_docstring(tmp_path: Path) -> None:
    cache = DocsCache(tmp_path)
    cache.set_state(
        "src/foo.py",
        FileDocState(
            path="src/foo.py",
            file_hash="h",
            functions={"add": FunctionDocState(hash="aaa", has_docstring=False)},
        ),
    )
    current = {"add": FunctionDocState(hash="aaa", has_docstring=False)}
    assert cache.needs_rerun("src/foo.py", current) == ["add"]


def test_schema_mismatch_evicts(tmp_path: Path) -> None:
    cache = DocsCache(tmp_path)
    cache.set_state("src/foo.py", make_state())
    entry = next((tmp_path / ".docspatch" / "cache" / "docs").iterdir())
    entry.write_bytes(gzip.compress(b'{"_schema_version": 999, "path": "x", "file_hash": "h", "functions": {}}'))

    fresh = DocsCache(tmp_path)
    assert fresh.get_state("src/foo.py") is None
    assert not entry.exists()
