"""Unified CONTEXT.md: project preamble + dir-grouped render with path markers, no LLM."""

from pathlib import Path

from docspatch.cache import ScoutCache
from docspatch.pipelines.readme.markers import readme_view
from docspatch.pipelines.scout.unified import (
    render_project_block,
    render_unified,
    resolve_internal_paths,
    write_unified,
)
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


def test_entry_point_module_renders_signature_and_docstring() -> None:
    cmd = FileSummary(
        path="src/pkg/cli.py",
        summary="The CLI.",
        functions=[
            FunctionMetadata(
                name="readme_cmd",
                signature="def readme_cmd(path=None, update=False, check=False) -> None",
                docstring="Generate a README.\n\nArgs:\n    update: Full rewrite.\n    check: Report staleness only.",
            )
        ],
    )
    out = render_unified([cmd], FACTS, None, {"pkg.cli"})
    assert "def readme_cmd(path=None, update=False, check=False)" in out
    assert "update: Full rewrite." in out  # argument help survives, not collapsed
    assert "check: Report staleness only." in out


def test_public_module_renders_detailed_signatures() -> None:
    # Every public module — not just entry points — carries its real signatures
    # and docstrings, the surface a README is written from.
    mod = FileSummary(
        path="src/pkg/util.py",
        summary="A helper.",
        functions=[FunctionMetadata(name="helper", signature="def helper() -> None", llm_summary="Does a thing.")],
    )
    out = render_unified([mod], FACTS, None, set())
    assert "def helper() -> None" in out
    assert "Does a thing." in out


def test_internal_module_stays_one_line() -> None:
    mod = FileSummary(
        path="src/pkg/wiring.py",
        summary="Plumbing.",
        functions=[FunctionMetadata(name="wire", signature="def wire() -> None", llm_summary="Wires things.")],
    )
    overview = ProjectOverviewOutput(summary="s", architecture="a", file_tiers={"src/pkg/wiring.py": "internal"})
    out = render_unified([mod], FACTS, overview)
    assert "- wire — Wires things." in out
    assert "def wire()" not in out  # no signature dump for internal modules


# ---- README tier -----------------------------------------------------------


def _overview_with_tiers(tiers: dict[str, str]) -> ProjectOverviewOutput:
    return ProjectOverviewOutput(summary="s", architecture="a", file_tiers=tiers)


def test_internal_block_marker_carries_tier() -> None:
    pub = FileSummary(path="src/cli.py", summary="entry")
    internal = FileSummary(path="src/plumbing.py", summary="wiring")
    overview = _overview_with_tiers({"src/cli.py": "public", "src/plumbing.py": "internal"})
    out = render_unified([pub, internal], FACTS, overview)
    assert '<!-- dp:file path="src/cli.py" -->' in out  # public stays bare
    assert '<!-- dp:file path="src/plumbing.py" tier="internal" -->' in out


def test_entry_point_floor_overrides_internal_tag() -> None:
    # Model wrongly tags the entry-point module internal; the S1 floor keeps it public.
    summaries = [FileSummary(path="src/pkg/cli.py", summary="entry")]
    overview = _overview_with_tiers({"src/pkg/cli.py": "internal"})
    internal = resolve_internal_paths(summaries, overview, {"pkg.cli"})
    assert internal == set()


def test_no_overview_drops_nothing() -> None:
    summaries = [FileSummary(path="src/x.py", summary="x")]
    assert resolve_internal_paths(summaries, None, set()) == set()


def test_tier_round_trips_into_readme_view() -> None:
    pub = FileSummary(path="src/cli.py", summary="entry point")
    internal = FileSummary(path="src/plumbing.py", summary="wiring")
    overview = _overview_with_tiers({"src/cli.py": "public", "src/plumbing.py": "internal"})
    text = render_unified([pub, internal], FACTS, overview)
    doc = readme_view(text, ".")
    assert [b.path for b in doc.files] == ["src/cli.py"]
