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
    MAX_CODE_LINES,
    TOP_ABORT,
    TOP_ACCEPT_ALL,
    TOP_REVIEW,
    Preview,
    RenderCtx,
    ReviewEntry,
    build_breadcrumb,
    build_code,
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


def test_renders_at_extreme_terminal_widths(tmp_path: Path) -> None:
    """Review panel renders at width 20 and 200 without crashing."""
    src = tmp_path / "mod.py"
    src.write_text("def foo():\n    return 1\n")
    entry = ReviewEntry(rel="mod.py", qualname="foo", docstring="Foo doc.")
    ctx = RenderCtx(idx=1, total=2, accepted_count=0, rejected_count=0)
    preview = build_previews([entry], tmp_path)[("mod.py", "foo")]

    for width in (20, 200):
        panel = render_review_panel(
            entry=entry,
            ctx=ctx,
            preview=preview,
            files=["mod.py", "other.py"],
            siblings=["foo"],
            console_width=width,
        )
        output = render_str(panel, width=width)
        assert "foo" in output


def test_explorer_collapses_done_pins_current_at_top() -> None:
    files = [f"f{i:02d}.py" for i in range(20)]
    tree = build_explorer(files, current="f05.py", max_lines=10)
    out = render_str(tree, width=40)
    assert "5 done" in out
    assert "f05.py" in out
    # Current row immediately follows the done summary.
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    done_idx = next(i for i, ln in enumerate(lines) if "5 done" in ln)
    assert "f05.py" in lines[done_idx + 1]


def test_explorer_truncates_upcoming_when_over_budget() -> None:
    files = [f"f{i:02d}.py" for i in range(50)]
    tree = build_explorer(files, current="f00.py", max_lines=8)
    out = render_str(tree, width=40)
    assert "more upcoming" in out
    # No done header since current is first.
    assert "done" not in out


def test_explorer_omits_done_header_on_first_file() -> None:
    tree = build_explorer(["a.py", "b.py", "c.py"], current="a.py", max_lines=10)
    out = render_str(tree, width=40)
    assert "done" not in out


def test_explorer_no_footer_when_everything_fits() -> None:
    tree = build_explorer(["a.py", "b.py", "c.py"], current="a.py", max_lines=10)
    out = render_str(tree, width=40)
    assert "more upcoming" not in out


def test_explorer_current_not_in_files_falls_back_to_first() -> None:
    tree = build_explorer(["a.py", "b.py"], current="ghost.py", max_lines=10)
    out = render_str(tree, width=40)
    assert "done" not in out
    assert "a.py" in out


def test_build_code_truncates_long_body() -> None:
    body = "def foo():\n" + "\n".join(f"    x{i} = {i}" for i in range(120))
    syntax = build_code(preview=Preview(code=body, start_line=1))
    out = render_str(syntax, width=80)
    assert "more body lines" in out


def test_build_code_keeps_signature_and_docstring_visible() -> None:
    body = 'def foo():\n    """The docstring under review."""\n' + "\n".join(
        f"    x{i} = {i}" for i in range(120)
    )
    out = render_str(build_code(preview=Preview(code=body, start_line=1)), width=80)
    assert "def foo" in out
    assert "docstring under review" in out


def test_build_code_no_footer_when_short() -> None:
    short = "def foo():\n    return 1\n"
    out = render_str(build_code(preview=Preview(code=short, start_line=1)), width=80)
    assert "more body lines" not in out


def test_build_code_respects_max_lines_override() -> None:
    body = "\n".join(f"line{i}" for i in range(20))
    out = render_str(build_code(preview=Preview(code=body, start_line=1), max_lines=5), width=80)
    assert "more body lines" in out


def test_max_code_lines_is_50() -> None:
    assert MAX_CODE_LINES == 50


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
