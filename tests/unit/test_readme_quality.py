"""README quality gate: deterministic findings and feedback folding."""

from docspatch.pipelines.readme.quality import findings_as_feedback, inspect_readme

_GOOD = "# demo\n\ndemo turns code into docs. Install with `uv sync`.\n"


def codes(md: str, *, project_name: str | None = "demo", entry_points: tuple[str, ...] = ()) -> list[str]:
    return [f.code for f in inspect_readme(md, project_name=project_name, entry_points=entry_points)]


def test_clean_readme_has_no_findings() -> None:
    assert inspect_readme(_GOOD, project_name="demo", entry_points=()) == []


def test_flags_marketing_language() -> None:
    assert "marketing" in codes("# demo\n\nA powerful, seamless, robust tool.\n")


def test_flags_missing_title() -> None:
    assert "no_title" in codes("demo does things.\n")


def test_flags_surrounding_code_fence() -> None:
    assert "fenced" in codes("```\n# demo\n```")


def test_flags_unnamed_project_at_root() -> None:
    assert "missing_name" in codes("# Tool\n\nIt does things.\n")


def test_subpackage_without_name_skips_name_check() -> None:
    assert "missing_name" not in codes("# auth\n\nLogin helpers.\n", project_name=None)


def test_feedback_lists_every_fix() -> None:
    findings = inspect_readme("```\nA powerful tool.\n```", project_name="demo", entry_points=())
    note = findings_as_feedback(findings)
    assert note.count("- ") == len(findings)
    assert "quality issues" in note.lower()


def test_flags_uncovered_declared_command() -> None:
    assert "entry_point_coverage" in codes("# demo\n\ndemo turns code into docs.\n", entry_points=("dp",))


def test_covered_command_passes() -> None:
    assert "entry_point_coverage" not in codes("# demo\n\nRun `dp readme` to generate docs.\n", entry_points=("dp",))


def test_coverage_is_a_noop_without_declared_commands() -> None:
    # A library or service that ships no console scripts is never held to a command bar.
    assert "entry_point_coverage" not in codes("# webapp\n\nStart it with the framework runner.\n", entry_points=())
