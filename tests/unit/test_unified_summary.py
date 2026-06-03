"""Unified CONTEXT.md: project preamble + dir-grouped render with path markers, no LLM."""

from pathlib import Path

from docspatch.cache import ScoutCache
from docspatch.pipelines.scout.unified import render_project_block, render_unified, write_unified
from docspatch.schemas import ComponentNote, FileSummary, FunctionMetadata, ProjectOverviewOutput
from docspatch.utils.project import ProjectFacts

FACTS = ProjectFacts(name="proj", description="a tool", labelled=[("Version", "1.0")])


def test_render_wraps_each_file_in_path_markers() -> None:
    s = FileSummary(
        path="src/x.py",
        summary="does x",
        interfaces=["f()"],
        relationships=["imports y"],
        functions=[FunctionMetadata(name="f", signature="def f()", llm_summary="runs f")],
    )
    out = render_unified([s], FACTS, None)
    assert '<!-- dp:file path="src/x.py" -->' in out
    assert "<!-- /dp:file -->" in out
    assert "does x" in out
    assert "f()" in out
    assert "imports y" in out
    assert "runs f" in out


def test_render_groups_by_directory_sorted() -> None:
    a = FileSummary(path="src/b/y.py", summary="y")
    b = FileSummary(path="src/a/x.py", summary="x")
    out = render_unified([a, b], FACTS, None)
    assert out.index('path="src/a/x.py"') < out.index('path="src/b/y.py"')


def test_project_block_facts_only_omits_architecture() -> None:
    out = render_project_block(FACTS, None)
    assert "<!-- dp:project -->" in out
    assert "# proj" in out
    assert "**Version:** 1.0" in out
    assert "## Architecture" not in out


def test_project_block_renders_overview_and_components() -> None:
    overview = ProjectOverviewOutput(
        summary="what it does",
        architecture="how it fits",
        components=[ComponentNote(name="core", role="runs things")],
    )
    out = render_project_block(FACTS, overview)
    assert "## Architecture" in out
    assert "what it does" in out
    assert "how it fits" in out
    assert "- **core** — runs things" in out


def test_render_puts_project_block_before_file_blocks() -> None:
    s = FileSummary(path="src/x.py", summary="does x")
    out = render_unified([s], FACTS, None)
    assert out.index("<!-- dp:project -->") < out.index('<!-- dp:file path="src/x.py" -->')


def test_write_unified_writes_file_from_cache(tmp_path: Path) -> None:
    cache = ScoutCache(tmp_path)
    cache.set("src/x.py", FileSummary(path="src/x.py", summary="does x"))
    out_path = write_unified(cache, ["src/x.py"], tmp_path, None)
    assert out_path == tmp_path / ".docspatch" / "CONTEXT.md"
    text = out_path.read_text()
    assert "<!-- dp:project -->" in text
    assert '<!-- dp:file path="src/x.py" -->' in text
    assert "does x" in text
