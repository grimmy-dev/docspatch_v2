"""Tests for the plan-time TargetRegistry lookup."""

from pathlib import Path

import pytest

from docspatch.pipelines.docs.planner import Target
from docspatch.pipelines.docs.registry import TargetRegistry
from docspatch.pipelines.docs.state import TargetRef
from docspatch.source import file_hash


def _target(rel: str, qualname: str, body: str = "pass") -> Target:
    return Target(file=Path(rel), rel=rel, qualname=qualname, signature="def f()", body=body)


def test_token_cost_and_get(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    t = _target("a.py", "f")
    reg = TargetRegistry.from_targets(tmp_path, [t])

    ref = TargetRef(rel="a.py", qualname="f")
    assert reg.token_cost(ref) == t.token_cost
    assert reg.get(ref) is t


def test_get_and_contains_miss(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    reg = TargetRegistry.from_targets(tmp_path, [_target("a.py", "f")])

    assert TargetRef(rel="a.py", qualname="f") in reg
    assert TargetRef(rel="a.py", qualname="missing") not in reg
    assert reg.get(TargetRef(rel="a.py", qualname="missing")) is None


def test_plan_hash_snapshots_disk(tmp_path: Path) -> None:
    source = "x = 1\n"
    (tmp_path / "a.py").write_text(source)
    reg = TargetRegistry.from_targets(tmp_path, [_target("a.py", "f")])

    assert reg.plan_hash("a.py") == file_hash(source)
    assert reg.plan_hash("other.py") is None


def test_one_hash_per_file(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    reg = TargetRegistry.from_targets(tmp_path, [_target("a.py", "f"), _target("a.py", "g")])

    assert list(reg.plan_hashes) == ["a.py"]
    assert TargetRef(rel="a.py", qualname="f") in reg
    assert TargetRef(rel="a.py", qualname="g") in reg


def test_registry_property_fails_fast_before_plan() -> None:
    from docspatch.pipelines.docs.context import GraphContext

    ctx = GraphContext.__new__(GraphContext)
    ctx._registry = None
    with pytest.raises(RuntimeError, match="before planning"):
        _ = ctx.registry
