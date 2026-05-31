"""Unified SUMMARY.md: dir-grouped render with path markers, no LLM."""

from pathlib import Path

from docspatch.cache import ScoutCache
from docspatch.pipelines.scout.unified import render_unified, write_unified
from docspatch.schemas import FileSummary, FunctionMetadata


def test_render_wraps_each_file_in_path_markers() -> None:
    s = FileSummary(
        path="src/x.py",
        summary="does x",
        interfaces=["f()"],
        relationships=["imports y"],
        functions=[FunctionMetadata(name="f", signature="def f()", llm_summary="runs f")],
    )
    out = render_unified([s])
    assert '<!-- dp:file path="src/x.py" -->' in out
    assert "<!-- /dp:file -->" in out
    assert "does x" in out
    assert "f()" in out
    assert "imports y" in out
    assert "runs f" in out


def test_render_groups_by_directory_sorted() -> None:
    a = FileSummary(path="src/b/y.py", summary="y")
    b = FileSummary(path="src/a/x.py", summary="x")
    out = render_unified([a, b])
    assert out.index('path="src/a/x.py"') < out.index('path="src/b/y.py"')


def test_write_unified_writes_file_from_cache(tmp_path: Path) -> None:
    cache = ScoutCache(tmp_path)
    cache.set("src/x.py", FileSummary(path="src/x.py", summary="does x"))
    out_path = write_unified(cache, ["src/x.py"], tmp_path)
    assert out_path == tmp_path / ".docspatch" / "SUMMARY.md"
    text = out_path.read_text()
    assert '<!-- dp:file path="src/x.py" -->' in text
    assert "does x" in text
