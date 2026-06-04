"""Marker selection: scope slicing and README projection of the unified CONTEXT.md."""

from docspatch.pipelines.readme.markers import (
    internal_module_names,
    parse_summary,
    readme_view,
    select,
    under_scope,
)
from docspatch.pipelines.scout.unified import MARKER_CLOSE, render_unified
from docspatch.schemas import FileSummary, FunctionMetadata
from docspatch.utils.project import ProjectFacts


def _summary_text():
    summaries = [
        FileSummary(path="src/auth/login.py", summary="Logs users in."),
        FileSummary(path="src/auth/tokens.py", summary="Issues tokens."),
        FileSummary(path="src/db/pool.py", summary="Pools connections."),
    ]
    facts = ProjectFacts(name="demo", description="A demo project.")
    return render_unified(summaries, facts, overview=None)


def test_parse_finds_project_and_every_file():
    doc = parse_summary(_summary_text())
    assert doc.project is not None
    assert {b.path for b in doc.files} == {"src/auth/login.py", "src/auth/tokens.py", "src/db/pool.py"}


def test_block_body_holds_the_summary_text():
    doc = parse_summary(_summary_text())
    login = next(b for b in doc.files if b.path == "src/auth/login.py")
    assert "Logs users in." in login.body
    assert "dp:file" not in login.body  # markers stripped from the inner body


def test_under_scope_nesting():
    assert under_scope("src/auth/login.py", "src/auth")
    assert under_scope("src/auth/login.py", "src/auth/")
    assert under_scope("src/auth/login.py", ".")
    assert not under_scope("src/auth/login.py", "src/db")
    # A sibling that merely shares a name prefix is not under scope.
    assert not under_scope("src/authority.py", "src/auth")


def test_select_subpackage_drops_project_and_out_of_scope_files():
    doc = select(_summary_text(), "src/auth")
    assert doc.project is None
    assert {b.path for b in doc.files} == {"src/auth/login.py", "src/auth/tokens.py"}


def test_select_root_keeps_project_and_all_files():
    doc = select(_summary_text(), ".")
    assert doc.project is not None
    assert len(doc.files) == 3


# ---- README projection (readme_view) --------------------------------------


def _text_with_functions():
    summaries = [
        FileSummary(
            path="src/auth/login.py",
            summary="Logs users in.",
            interfaces=["login", "logout"],
            relationships=["depends on tokens.py"],
            functions=[
                FunctionMetadata(name="login", signature="()", llm_summary="Authenticate a user."),
                FunctionMetadata(name="logout", signature="()", llm_summary="End a session."),
            ],
        ),
    ]
    return render_unified(summaries, ProjectFacts(name="demo"), overview=None)


def test_readme_view_keeps_public_surface_and_function_detail():
    # Public modules are written from their real signatures and docstrings, so the
    # README view keeps the function detail intact — it is not stripped.
    doc = readme_view(_text_with_functions(), ".")
    login = next(b for b in doc.files if b.path == "src/auth/login.py")
    assert "Logs users in." in login.body
    assert "**Interfaces:**" in login.body
    assert "**Relationships:**" in login.body
    assert "Authenticate a user." in login.body
    assert "End a session." in login.body


def _text_with_tiers():
    # Hand-built CONTEXT text carrying explicit tier attributes on the markers.
    return (
        '<!-- dp:file path="src/cli.py" tier="public" -->\n'
        "## cli.py\nThe entry point.\n"
        f"{MARKER_CLOSE}\n"
        '<!-- dp:file path="src/internal/plumbing.py" tier="internal" -->\n'
        "## plumbing.py\nInternal wiring.\n"
        f"{MARKER_CLOSE}\n"
    )


def test_parse_reads_tier_attribute():
    doc = parse_summary(_text_with_tiers())
    tiers = {b.path: b.tier for b in doc.files}
    assert tiers == {"src/cli.py": "public", "src/internal/plumbing.py": "internal"}


def test_parse_defaults_tier_public_when_absent():
    doc = parse_summary(_summary_text())
    assert all(b.tier == "public" for b in doc.files)


def test_readme_view_drops_internal_tier_blocks():
    doc = readme_view(_text_with_tiers(), ".")
    assert [b.path for b in doc.files] == ["src/cli.py"]


def test_internal_module_names_returns_stems():
    assert internal_module_names(_text_with_tiers(), ".") == ["plumbing"]


def _text_internal_subpackage():
    # A whole subpackage tagged internal at the project level.
    return (
        '<!-- dp:file path="src/ui/panel.py" tier="internal" -->\n'
        "## panel.py\nRenders panels.\n"
        f"{MARKER_CLOSE}\n"
        '<!-- dp:file path="src/ui/table.py" tier="internal" -->\n'
        "## table.py\nRenders tables.\n"
        f"{MARKER_CLOSE}\n"
    )


def test_subpackage_scope_keeps_internal_blocks():
    # Scoping a README to the subpackage makes it the subject; internal-tier
    # blocks under that scope must not be dropped, or there is nothing to document.
    doc = readme_view(_text_internal_subpackage(), "src/ui")
    assert {b.path for b in doc.files} == {"src/ui/panel.py", "src/ui/table.py"}


def test_root_scope_still_drops_internal_blocks():
    doc = readme_view(_text_internal_subpackage(), ".")
    assert doc.files == []
