"""README prompt assembly: scope-aware facts, feedback, and remarks."""

from docspatch.pipelines.readme.markers import FileBlock
from docspatch.pipelines.readme.prompts import (
    ReadmeContext,
    build_refine_prompt,
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


def test_refine_prompt_carries_draft_backbone_and_new_modules():
    ctx = _root_ctx(project_overview="## Architecture\nPipeline synthesis.")
    prompt = build_refine_prompt(ctx, "# Demo\n\nrunning draft", _BLOCKS)
    assert "running draft" in prompt
    assert "Logs users in." in prompt  # the next batch's summaries
    assert "Project name: demo" in prompt  # backbone identity every fold step
    assert "Pipeline synthesis." in prompt


def test_root_prompt_includes_project_overview():
    ctx = _root_ctx(project_overview="## Architecture\nGraph-based pipeline synthesis.")
    prompt = build_single_prompt(ctx, _BLOCKS)
    assert "Project overview" in prompt
    assert "Graph-based pipeline synthesis." in prompt


def test_subpackage_prompt_omits_project_overview():
    # select() nulls the overview off root, so a subpackage ctx never carries it.
    prompt = build_single_prompt(_sub_ctx(), _BLOCKS)
    assert "Project overview" not in prompt


def test_single_and_refine_both_carry_the_backbone():
    ctx = _root_ctx(project_overview="## Architecture\nPipeline synthesis.")
    single = build_single_prompt(ctx, _BLOCKS)
    refine = build_refine_prompt(ctx, "# Demo\n\ndraft", _BLOCKS)
    for prompt in (single, refine):
        assert "Project name: demo" in prompt  # facts
        assert "Pipeline synthesis." in prompt  # overview
        assert "Directory layout:" in prompt  # tree


def test_existing_readme_instruction_preserves_adds_and_drops():
    prompt = build_single_prompt(_root_ctx(existing_readme="# Demo\n## Usage\ntext"), _BLOCKS)
    assert "copy it through byte-for-byte" in prompt  # no cosmetic reflow of unchanged text
    assert "README omits" in prompt  # additive: surface missing docs
    assert "has been deleted" in prompt  # subtractive: drop gone features
    assert "Keep its structure" in prompt


def test_ground_rules_state_required_sections_and_tier_guard():
    prompt = build_single_prompt(_root_ctx(), _BLOCKS)
    assert "declared entry points or public API" in prompt
    assert "public surface" in prompt


def test_ground_rules_forbid_fabricated_signatures():
    prompt = build_single_prompt(_root_ctx(), _BLOCKS)
    assert "Never invent or guess one" in prompt


def test_ground_rules_ask_for_how_it_works_from_overview():
    prompt = build_single_prompt(_root_ctx(), _BLOCKS)
    assert "How it works" in prompt


def test_rewrite_mode_allows_restructure_but_keeps_curated_sections():
    ctx = _root_ctx(existing_readme="# Demo\n## License\nMIT", rewrite=True)
    prompt = build_single_prompt(ctx, _BLOCKS)
    assert "rewrite it: you may restructure" in prompt
    assert "keep every section that carries real content" in prompt
    assert "copy it through byte-for-byte" not in prompt  # not the verbatim mode


def test_refresh_mode_is_the_default_and_preserves_verbatim():
    ctx = _root_ctx(existing_readme="# Demo\n## License\nMIT")
    prompt = build_single_prompt(ctx, _BLOCKS)
    assert "copy it through byte-for-byte" in prompt
    assert "you may restructure" not in prompt
