"""store_summary persistence: new summary fields and change_note rules."""

import asyncio
from pathlib import Path

from docspatch.cache import ScoutCache
from docspatch.pipelines.scout.state import FileMiss
from docspatch.pipelines.scout.summarize import store_summary
from docspatch.schemas import FileSummary, FileSummaryOutput


def _seed(tmp_path: Path, body: str = "def a():\n    return 1\n") -> ScoutCache:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text(body)
    return ScoutCache(tmp_path)


def test_store_summary_persists_new_fields(tmp_path):
    cache = _seed(tmp_path)
    prior = FileSummary(path="src/a.py", summary="old", compressed="def a(): return 0")
    miss = FileMiss("src/a.py", "def a():\n    return 1\n", "def a(): return 1", "NEW", prior=prior)
    out = FileSummaryOutput(summary="new", interfaces=["a()"], relationships=["none"], change_note="changed return")
    asyncio.run(store_summary(cache, miss, out))

    got = ScoutCache(tmp_path).get("src/a.py")
    assert got is not None
    assert got.interfaces == ["a()"]
    assert got.relationships == ["none"]
    assert got.change_note == "changed return"
    assert got.compressed == "def a(): return 1"


def test_store_summary_forces_null_change_note_for_new_file(tmp_path):
    cache = _seed(tmp_path)
    miss = FileMiss("src/a.py", "def a():\n    return 1\n", "def a(): return 1", "NEW")
    out = FileSummaryOutput(summary="new", change_note="model should not have set this")
    asyncio.run(store_summary(cache, miss, out))

    got = ScoutCache(tmp_path).get("src/a.py")
    assert got is not None
    assert got.change_note is None
