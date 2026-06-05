"""README prompt assembly: triage, drill, and generator builders."""

from docspatch.pipelines.readme.prompts import (
    build_drill_prompt,
    build_generator_prompt,
    build_triage_prompt,
    render_backbone,
    render_surface,
    scope_label,
)
from docspatch.pipelines.readme.state import PreContext, Surface, SurfaceEntry
from docspatch.utils.project import ProjectFacts


def make_pre(scope: str = ".") -> PreContext:
    return PreContext(
        scope=scope,
        tagged_tree="cli.py [new]\nutils.py",
        facts=ProjectFacts(name="demo", description="A demo."),
        dependencies=("typer",),
        entry_points=("dp",),
        entry_point_modules=frozenset({"cli"}),
        tool_defs="TOOLDEF-MARKER",
    )


def test_scope_label_root_vs_package() -> None:
    assert scope_label(".") == "the whole project"
    assert scope_label("src/auth") == "the `src/auth` package"


def test_backbone_carries_facts_and_tagged_tree() -> None:
    bb = render_backbone(make_pre())
    assert "Project name: demo" in bb
    assert "typer" in bb
    assert "cli.py [new]" in bb


def test_triage_prompt_has_tree_and_tool_menu() -> None:
    prompt = build_triage_prompt(make_pre())
    assert "cli.py [new]" in prompt
    assert "TOOLDEF-MARKER" in prompt


def test_drill_prompt_includes_surfaces_and_demands_synthesis() -> None:
    prompt = build_drill_prompt(make_pre(), "### cli.py\n- def main()", error=None)
    assert "### cli.py" in prompt
    assert "synthesis" in prompt.lower()


def test_drill_prompt_surfaces_retry_error() -> None:
    prompt = build_drill_prompt(make_pre(), "### cli.py", error="not in the surfaces: ghost.py::x")
    assert "ghost.py::x" in prompt


def test_generator_prompt_frames_existing_readme_and_feedback() -> None:
    prompt = build_generator_prompt(".", woven="WOVEN-CTX", existing_readme="# Old\n\nkeep", feedback="be terse")
    assert "WOVEN-CTX" in prompt
    assert "keep" in prompt
    assert "be terse" in prompt


def test_generator_prompt_fresh_has_no_existing_block() -> None:
    prompt = build_generator_prompt(".", woven="WOVEN-CTX", existing_readme=None, feedback=None)
    assert "Existing README" not in prompt
    assert "WOVEN-CTX" in prompt


def test_render_surface_is_signature_and_docstring_only() -> None:
    s = Surface("m.py", "Mod.", [SurfaceEntry("function", "run", "def run() -> int", "Run it.")])
    rendered = render_surface(s)
    assert "def run() -> int" in rendered
    assert "Run it." in rendered
