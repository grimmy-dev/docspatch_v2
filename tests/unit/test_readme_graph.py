"""README context-resolution subgraph: happy path, empty triage, bad-plan retry."""

import asyncio
from pathlib import Path

from docspatch.llm import TokenUsage
from docspatch.pipelines.readme.graph import build_readme_graph
from docspatch.pipelines.readme.state import BodyRequest, DrillPlan, PreContext, ReadmeState, TriageSelection

SAMPLE = '''"""CLI module."""


def main() -> None:
    """Entry point."""
    helper()


def helper() -> int:
    return 41 + 1
'''


class FakeChain:
    """Returns queued values; repeats the last once exhausted."""

    def __init__(self, values: list) -> None:
        self.values = values
        self.calls = 0

    async def ainvoke(self, prompt: str):  # noqa: ANN201
        value = self.values[min(self.calls, len(self.values) - 1)]
        self.calls += 1
        return value, TokenUsage(10, 5)


class FakeClient:
    def __init__(self, triage: FakeChain, drill: FakeChain) -> None:
        self._triage = triage
        self._drill = drill

    def with_structured_output(self, schema: type):  # noqa: ANN201
        return self._triage if schema is TriageSelection else self._drill


def make_pre(scope: str = ".") -> PreContext:
    return PreContext(
        scope=scope,
        tagged_tree="cli.py",
        facts=None,
        dependencies=(),
        entry_points=("dp",),
        entry_point_modules=frozenset({"cli"}),
        tool_defs="",
    )


def initial_state(pre: PreContext) -> ReadmeState:
    return {
        "phase": "triage",
        "retry_count": 0,
        "revision_count": 0,
        "feedback": None,
        "selected_paths": [],
        "synthesis": None,
        "body_requests": [],
        "drill_error": None,
        "pre_context": pre,
        "surfaces": {},
        "bodies": {},
        "woven": None,
        "existing_readme": None,
        "markdown": None,
        "usage": TokenUsage(),
    }


def run(root: Path, triage: FakeChain, drill: FakeChain, pre: PreContext) -> ReadmeState:
    graph = build_readme_graph(root, FakeClient(triage, drill))
    return asyncio.run(graph.ainvoke(initial_state(pre)))


def test_happy_path_weaves_surface_and_body(tmp_path: Path) -> None:
    (tmp_path / "cli.py").write_text(SAMPLE)
    triage = FakeChain([TriageSelection(paths=["cli.py"])])
    drill = FakeChain([DrillPlan(bodies=[BodyRequest(path="cli.py", function_name="main")], synthesis="It runs.")])
    out = run(tmp_path, triage, drill, make_pre())
    assert "It runs." in out["woven"]
    assert "cli.py::main" in out["woven"]  # drilled body block
    assert out["usage"].input_tokens == 20  # triage + drill


def test_empty_triage_still_synthesizes(tmp_path: Path) -> None:
    triage = FakeChain([TriageSelection(paths=[])])
    drill = FakeChain([DrillPlan(bodies=[], synthesis="Tiny project.")])
    out = run(tmp_path, triage, drill, make_pre())
    assert "Tiny project." in out["woven"]
    assert out["surfaces"] == {}


def test_bad_plan_triggers_retry_then_proceeds(tmp_path: Path) -> None:
    (tmp_path / "cli.py").write_text(SAMPLE)
    triage = FakeChain([TriageSelection(paths=["cli.py"])])
    drill = FakeChain(
        [
            DrillPlan(bodies=[BodyRequest(path="ghost.py", function_name="nope")], synthesis="v1"),
            DrillPlan(bodies=[BodyRequest(path="cli.py", function_name="main")], synthesis="v2"),
        ]
    )
    out = run(tmp_path, triage, drill, make_pre())
    assert out["retry_count"] == 1
    assert drill.calls == 2  # re-drilled after bad plan
    assert "cli.py::main" in out["woven"]


def test_retry_exhaustion_proceeds_with_partial(tmp_path: Path) -> None:
    (tmp_path / "cli.py").write_text(SAMPLE)
    triage = FakeChain([TriageSelection(paths=["cli.py"])])
    # always names a non-surfaced function — never satisfiable
    drill = FakeChain([DrillPlan(bodies=[BodyRequest(path="ghost.py", function_name="nope")], synthesis="s")])
    out = run(tmp_path, triage, drill, make_pre())
    assert out["retry_count"] == 2  # MAX_RETRIES
    assert out["bodies"] == {}
    assert "s" in out["woven"]
