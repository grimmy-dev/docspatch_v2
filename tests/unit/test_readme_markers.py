"""Marker selection: scope slicing of the unified CONTEXT.md."""

from docspatch.pipelines.readme.markers import parse_summary, select, under_scope
from docspatch.pipelines.scout.unified import render_unified
from docspatch.schemas import FileSummary
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
