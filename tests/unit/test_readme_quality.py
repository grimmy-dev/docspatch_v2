"""README quality gate: deterministic findings and feedback folding."""

from docspatch.pipelines.readme.prompts import ReadmeContext
from docspatch.pipelines.readme.quality import findings_as_feedback, inspect_readme
from docspatch.utils.project import ProjectFacts

_GOOD = "# demo\n\ndemo turns code into docs. Install with `uv sync`.\n"


def _ctx(**kw):
    facts = ProjectFacts(name="demo", description="A demo.", labelled=[])
    return ReadmeContext(scope=".", dir_tree="src", facts=facts, **kw)


def test_clean_readme_has_no_findings():
    assert inspect_readme(_GOOD, _ctx()) == []


def test_flags_marketing_language():
    md = "# demo\n\nA powerful, seamless, robust tool.\n"
    codes = [f.code for f in inspect_readme(md, _ctx())]
    assert "marketing" in codes


def test_flags_missing_title():
    codes = [f.code for f in inspect_readme("demo does things.\n", _ctx())]
    assert "no_title" in codes


def test_flags_surrounding_code_fence():
    codes = [f.code for f in inspect_readme("```\n# demo\n```", _ctx())]
    assert "fenced" in codes


def test_flags_unnamed_project_at_root():
    codes = [f.code for f in inspect_readme("# Tool\n\nIt does things.\n", _ctx())]
    assert "missing_name" in codes


def test_subpackage_without_facts_skips_name_check():
    ctx = ReadmeContext(scope="src/auth", dir_tree="auth")
    codes = [f.code for f in inspect_readme("# auth\n\nLogin helpers.\n", ctx)]
    assert "missing_name" not in codes


def test_feedback_lists_every_fix():
    findings = inspect_readme("```\nA powerful tool.\n```", _ctx())
    note = findings_as_feedback(findings)
    assert note.count("- ") == len(findings)
    assert "quality issues" in note.lower()


# ---- entry-point coverage --------------------------------------------------


def test_flags_uncovered_declared_command():
    md = "# demo\n\ndemo turns code into docs.\n"
    codes = [f.code for f in inspect_readme(md, _ctx(entry_points=("dp",)))]
    assert "entry_point_coverage" in codes


def test_covered_command_passes():
    md = "# demo\n\nRun `dp readme` to generate docs.\n"
    codes = [f.code for f in inspect_readme(md, _ctx(entry_points=("dp",)))]
    assert "entry_point_coverage" not in codes


def test_coverage_is_a_noop_without_declared_commands():
    # A library, web server, or full-stack app that ships no console scripts is
    # never held to a command-coverage bar.
    md = "# webapp\n\nStart it with the framework runner.\n"
    ctx = _ctx(entry_points=())
    assert all(f.code != "entry_point_coverage" for f in inspect_readme(md, ctx))


# ---- internal leakage ------------------------------------------------------


def test_flags_internal_module_used_as_heading():
    md = "# demo\n\nintro.\n\n## pool\n\nConnection pool internals.\n"
    codes = [f.code for f in inspect_readme(md, _ctx(internal_modules=("pool",)))]
    assert "internal_leakage" in codes


def test_internal_name_in_prose_only_is_not_leakage():
    md = "# demo\n\nThe pool keeps connections warm.\n"
    codes = [f.code for f in inspect_readme(md, _ctx(internal_modules=("pool",)))]
    assert "internal_leakage" not in codes
