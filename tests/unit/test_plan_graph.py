"""Batch sizing in the plan graph, exercised without a full graph run.

Extracting the TargetRegistry let batch_targets be driven from a minimal context
instead of only through an end-to-end docs run.
"""

from pathlib import Path

from docspatch.pipelines.docs.context import GraphContext
from docspatch.pipelines.docs.plan_graph import batch_targets
from docspatch.pipelines.docs.planner import Target
from docspatch.pipelines.docs.registry import TargetRegistry
from docspatch.pipelines.docs.state import TargetRef


def _target(qualname: str, cost_tokens: int) -> Target:
    # token_cost == (len(signature) + len(body)) // 4; pad body to hit the target.
    body = "x" * (cost_tokens * 4)
    return Target(file=Path("m.py"), rel="m.py", qualname=qualname, signature="", body=body)


def _ctx(targets: list[Target], *, limit: int) -> GraphContext:
    ctx = GraphContext.__new__(GraphContext)
    ctx._registry = TargetRegistry(targets={(t.rel, t.qualname): t for t in targets}, plan_hashes={})
    ctx.batch_token_limit = limit
    return ctx


def test_empty_targets_yields_no_batches() -> None:
    ctx = _ctx([], limit=100)
    assert batch_targets(ctx, []) == []


def test_targets_split_when_over_limit() -> None:
    targets = [_target("a", 100), _target("b", 100)]
    ctx = _ctx(targets, limit=150)
    refs = [TargetRef(rel="m.py", qualname=t.qualname) for t in targets]

    batches = batch_targets(ctx, refs)
    assert len(batches) == 2  # 100 + 100 exceeds 150, so one per batch


def test_targets_packed_when_under_limit() -> None:
    targets = [_target("a", 100), _target("b", 100)]
    ctx = _ctx(targets, limit=250)
    refs = [TargetRef(rel="m.py", qualname=t.qualname) for t in targets]

    batches = batch_targets(ctx, refs)
    assert len(batches) == 1
    assert {r.qualname for r in batches[0].targets} == {"a", "b"}


def test_offset_shifts_batch_ids() -> None:
    targets = [_target("a", 100)]
    ctx = _ctx(targets, limit=250)
    refs = [TargetRef(rel="m.py", qualname="a")]

    assert batch_targets(ctx, refs, offset=5)[0].id == 5
