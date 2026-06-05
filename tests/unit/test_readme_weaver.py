"""Weaver: relevance tiering and surface/body dedup."""

from docspatch.pipelines.readme.state import PreContext, Surface, SurfaceEntry
from docspatch.pipelines.readme.weaver import body_key, relevance_tier, weave


def make_pre(modules: frozenset[str] = frozenset()) -> PreContext:
    return PreContext(
        scope=".",
        tagged_tree="src\n  cli.py",
        facts=None,
        dependencies=(),
        entry_points=(),
        entry_point_modules=modules,
        tool_defs="",
    )


def test_relevance_tier_orders_entry_pipeline_rest() -> None:
    mods = frozenset({"pkg.cli"})
    assert relevance_tier("pkg/cli.py", mods) == 0
    assert relevance_tier("pipelines/readme/graph.py", mods) == 1
    assert relevance_tier("utils/fs.py", mods) == 2


def test_weave_orders_entry_point_surface_first() -> None:
    pre = make_pre(frozenset({"pkg.cli"}))
    surfaces = {
        "utils/fs.py": Surface("utils/fs.py", None, [SurfaceEntry("function", "helper", "def helper()")]),
        "pkg/cli.py": Surface("pkg/cli.py", None, [SurfaceEntry("function", "main", "def main()")]),
    }
    woven = weave(pre, "Does things.", surfaces, {})
    assert woven.index("pkg/cli.py") < woven.index("utils/fs.py")
    assert "Does things." in woven
    assert "Shared understanding" in woven


def test_weave_drops_stub_when_body_drilled() -> None:
    pre = make_pre()
    surfaces = {
        "m.py": Surface("m.py", None, [SurfaceEntry("function", "run", "def run()"), SurfaceEntry("function", "aux", "def aux()")]),
    }
    bodies = {body_key("m.py", "run"): "def run():\n return 1"}
    woven = weave(pre, "S.", surfaces, bodies)
    # full body present, the run stub gone, aux stub kept
    assert "def run():\n return 1" in woven
    assert "- def run()" not in woven
    assert "- def aux()" in woven
