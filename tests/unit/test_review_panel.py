"""Review panel: session flow (accept-all / per-item / abort / rerun) + rendering."""

from io import StringIO
from pathlib import Path

from rich.console import Console

from docspatch.ui.prompter import ScriptedPrompter
from docspatch.ui.review_panel import (
    ITEM_ACCEPT,
    ITEM_BACK,
    ITEM_REJECT,
    ITEM_RERUN,
    TOP_ABORT,
    TOP_ACCEPT_ALL,
    TOP_REVIEW,
    Preview,
    RenderCtx,
    ReviewEntry,
    build_breadcrumb,
    build_explorer,
    build_previews,
    item_menu,
    render_review_panel,
    review_session,
)


def seed(tmp_path: Path) -> list[dict]:
    """Two undocumented functions in one file, as an interrupt payload would carry them."""
    src = tmp_path / "mod.py"
    src.write_text("def foo():\n    return 1\n\n\ndef bar():\n    return 2\n")
    return [
        {"rel": "mod.py", "qualname": "foo", "docstring": "Foo doc."},
        {"rel": "mod.py", "qualname": "bar", "docstring": "Bar doc."},
    ]


def run(tmp_path: Path, answers: list[object], *, allow_rerun: bool = True) -> dict:
    return review_session(
        seed(tmp_path),
        repo_root=tmp_path,
        prompter=ScriptedPrompter(answers),
        allow_rerun=allow_rerun,
    )


def test_build_previews_handles_module_docstring(tmp_path: Path) -> None:
    src = tmp_path / "mod.py"
    src.write_text("import os\n\n\ndef f():\n    return os\n")

    previews = build_previews(
        [ReviewEntry(rel="mod.py", qualname="<module>", docstring="Module doc.")], tmp_path
    )

    preview = previews[("mod.py", "<module>")]
    assert '"""Module doc."""' in preview.code
    assert preview.start_line == 1


def test_empty_entries_returns_empty_choice(tmp_path: Path) -> None:
    choice = review_session([], repo_root=tmp_path, prompter=ScriptedPrompter([]), allow_rerun=True)
    assert choice == {"accepted": [], "rejected": [], "rerun": [], "feedback": {}, "aborted": False}


def test_accept_all_accepts_every_entry(tmp_path: Path) -> None:
    choice = run(tmp_path, [TOP_ACCEPT_ALL])
    assert sorted(choice["accepted"]) == ["mod.py::bar", "mod.py::foo"]
    assert choice["aborted"] is False


def test_abort_sets_aborted_flag(tmp_path: Path) -> None:
    choice = run(tmp_path, [TOP_ABORT])
    assert choice["accepted"] == []
    assert choice["aborted"] is True


def test_per_item_mixed_accept_reject(tmp_path: Path) -> None:
    choice = run(tmp_path, [TOP_REVIEW, ITEM_ACCEPT, ITEM_REJECT])
    assert choice["accepted"] == ["mod.py::foo"]
    assert choice["rejected"] == ["mod.py::bar"]


def test_back_to_menu_then_accept_all_sweeps_unreviewed_only(tmp_path: Path) -> None:
    choice = run(tmp_path, [TOP_REVIEW, ITEM_ACCEPT, ITEM_BACK, TOP_ACCEPT_ALL])
    assert choice["accepted"] == ["mod.py::foo", "mod.py::bar"]
    assert choice["rejected"] == []


def test_rerun_queues_entry_and_collects_feedback(tmp_path: Path) -> None:
    choice = run(tmp_path, [TOP_REVIEW, ITEM_RERUN, "needs more detail", ITEM_ACCEPT])
    assert choice["rerun"] == ["mod.py::foo"]
    assert choice["feedback"] == {"mod.py::foo": "needs more detail"}
    assert choice["accepted"] == ["mod.py::bar"]


def test_allow_rerun_false_hides_rerun_choice(tmp_path: Path) -> None:
    seen: list[dict[str, str]] = []

    class CapturePrompter(ScriptedPrompter):
        def select(self, question: str, choices, default=None):  # type: ignore[override]
            seen.append(dict(choices))
            return super().select(question, choices, default)

    review_session(
        seed(tmp_path),
        repo_root=tmp_path,
        prompter=CapturePrompter([TOP_REVIEW, ITEM_ACCEPT, ITEM_ACCEPT]),
        allow_rerun=False,
    )
    item_menus = [c for c in seen if "Accept" in c]
    assert item_menus
    for menu in item_menus:
        assert "Rerun with feedback" not in menu


def test_preview_includes_docstring_and_signature_only(tmp_path: Path) -> None:
    src = tmp_path / "mod.py"
    src.write_text("def foo():\n    return 1\n\n\ndef bar():\n    return 2\n")
    entries = [ReviewEntry(rel="mod.py", qualname="foo", docstring="Preview marker.")]
    preview = build_previews(entries, tmp_path)[("mod.py", "foo")]
    assert "Preview marker." in preview.code
    assert "def foo" in preview.code
    assert "return 1" not in preview.code
    assert preview.start_line == 1


def test_preview_handles_class_method(tmp_path: Path) -> None:
    src = tmp_path / "mod.py"
    src.write_text("class C:\n    def m(self):\n        return 1\n")
    entries = [ReviewEntry(rel="mod.py", qualname="C.m", docstring="Method doc.")]
    preview = build_previews(entries, tmp_path)[("mod.py", "C.m")]
    assert "Method doc." in preview.code
    assert "def m" in preview.code
    assert "return 1" not in preview.code


def render_str(renderable: object, width: int) -> str:
    buf = StringIO()
    Console(file=buf, width=width, force_terminal=False, color_system=None).print(renderable)
    return buf.getvalue()


def test_breadcrumb_shows_path_qualname_and_position() -> None:
    entry = ReviewEntry(rel="prds/test.py", qualname="dijkstra", docstring="d")
    text = build_breadcrumb(entry=entry, siblings=["foo", "dijkstra", "bar"]).plain
    assert "prds/test.py" in text
    assert "dijkstra" in text
    assert "(2/3 in file)" in text


def test_explorer_groups_files_by_directory() -> None:
    tree = build_explorer(["prds/test.py", "prds/complex.py", "src/main.py"], current="prds/test.py")
    output = render_str(tree, width=40)
    assert "prds/" in output
    assert "src/" in output
    assert "main.py" in output


def test_explorer_truncates_long_filenames() -> None:
    long = "deeply/nested/path/to/some_very_long_module_name.py"
    assert "…" in render_str(build_explorer([long], current=long), width=40)


def test_sidebar_hidden_for_single_file() -> None:
    entry = ReviewEntry(rel="a.py", qualname="foo", docstring="d")
    output = render_str(
        render_review_panel(
            entry=entry,
            ctx=RenderCtx(idx=1, total=1, accepted_count=0, rejected_count=0),
            preview=Preview(code="def foo(): ...", start_line=1),
            files=["a.py"],
            siblings=["foo"],
            console_width=160,
        ),
        width=160,
    )
    assert "EXPLORER" not in output


def test_sidebar_visible_for_multi_file() -> None:
    entry = ReviewEntry(rel="a.py", qualname="foo", docstring="d")
    output = render_str(
        render_review_panel(
            entry=entry,
            ctx=RenderCtx(idx=1, total=2, accepted_count=0, rejected_count=0),
            preview=Preview(code="def foo(): ...", start_line=1),
            files=["a.py", "b.py"],
            siblings=["foo"],
            console_width=160,
        ),
        width=160,
    )
    assert "EXPLORER" in output


# --- parse-failed entries ---


def test_parse_failed_item_menu_has_no_accept() -> None:
    failed = ReviewEntry(rel="m.py", qualname="f", docstring="", parse_failed=True)
    ok = ReviewEntry(rel="m.py", qualname="g", docstring="doc")
    assert "Accept" not in item_menu(failed, allow_rerun=True)
    assert "Accept" in item_menu(ok, allow_rerun=True)
    assert "Reject" in item_menu(failed, allow_rerun=True)


def test_accept_all_rejects_parse_failed_entry(tmp_path: Path) -> None:
    src = tmp_path / "mod.py"
    src.write_text("def foo():\n    return 1\n")
    entries = [
        {"rel": "mod.py", "qualname": "foo", "docstring": "", "parse_failed": True, "raw_output": "not json"},
    ]
    choice = review_session(
        entries, repo_root=tmp_path, prompter=ScriptedPrompter([TOP_ACCEPT_ALL]), allow_rerun=True
    )
    assert choice["accepted"] == []
    assert choice["rejected"] == ["mod.py::foo"]


def test_parse_failed_panel_shows_raw_output() -> None:
    entry = ReviewEntry(rel="m.py", qualname="f", docstring="", parse_failed=True, raw_output="GARBAGE_123")
    output = render_str(
        render_review_panel(
            entry=entry,
            ctx=RenderCtx(idx=1, total=1, accepted_count=0, rejected_count=0),
            preview=Preview(code="", start_line=1),
            files=["m.py"],
            siblings=["f"],
            console_width=100,
        ),
        width=100,
    )
    assert "PARSE FAILED" in output
    assert "GARBAGE_123" in output
