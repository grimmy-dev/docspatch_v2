"""README prompt assembly: scope-aware facts, feedback, and remarks."""

from docspatch.pipelines.readme.markers import FileBlock
from docspatch.pipelines.readme.prompts import (
    ReadmeContext,
    build_map_prompt,
    build_reduce_prompt,
    build_single_prompt,
)
from docspatch.utils.project import ProjectFacts

_BLOCKS = [FileBlock(path="src/auth/login.py", body="## login.py\nLogs users in.")]


def _root_ctx(**kw):
    facts = ProjectFacts(name="demo", description="A demo.", labelled=[("Python", ">=3.14")])
    base = dict(scope=".", dir_tree="src\n  auth", facts=facts, dependencies=("rich>=13",))
    return ReadmeContext(**{**base, **kw})


def _sub_ctx(**kw):
    base = dict(scope="src/auth", dir_tree="auth\n  login.py")
    return ReadmeContext(**{**base, **kw})


def test_root_prompt_includes_pyproject_facts_and_deps():
    prompt = build_single_prompt(_root_ctx(), _BLOCKS)
    assert "Project name: demo" in prompt
    assert "Python: >=3.14" in prompt
    assert "Dependencies: rich>=13" in prompt
    assert "whole project" in prompt


def test_subpackage_prompt_omits_pyproject_facts():
    prompt = build_single_prompt(_sub_ctx(), _BLOCKS)
    assert "Project facts" not in prompt
    assert "Dependencies" not in prompt
    assert "`src/auth` package" in prompt


def test_feedback_and_remarks_appended_oldest_first():
    ctx = _root_ctx(remarks="keep it short", feedback=("add install steps", "mention license"))
    prompt = build_single_prompt(ctx, _BLOCKS)
    assert "keep it short" in prompt
    assert prompt.index("add install steps") < prompt.index("mention license")


def test_existing_readme_included_when_present():
    prompt = build_single_prompt(_root_ctx(existing_readme="# Demo\n[![ci](x)](y)"), _BLOCKS)
    assert "Existing README" in prompt
    assert "[![ci](x)](y)" in prompt


def test_reduce_prompt_merges_sections():
    prompt = build_reduce_prompt(_root_ctx(), ["## A\ntext", "## B\ntext"])
    assert "Merge the draft sections" in prompt
    assert "## A" in prompt and "## B" in prompt


def test_map_prompt_is_section_scoped():
    prompt = build_map_prompt(_sub_ctx(), _BLOCKS)
    assert "focused README section" in prompt
    assert "Logs users in." in prompt
