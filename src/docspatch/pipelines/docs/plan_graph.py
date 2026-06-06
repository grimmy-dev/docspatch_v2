"""LangGraph state machine definitions and nodes for tracking and executing the documentation planning phases."""

from collections import defaultdict

from langgraph.graph import END, START, StateGraph

from docspatch.llm.catalogue import tier_info
from docspatch.llm.pricing import estimate_cost
from docspatch.pipelines.docs.context import GraphContext
from docspatch.pipelines.docs.planner import collect_targets
from docspatch.pipelines.docs.registry import TargetRegistry
from docspatch.pipelines.docs.state import BatchRef, CostBreakdown, PlanState, TargetRef
from docspatch.ui import console, cost_panel, status, warning_panel
from docspatch.utils.batcher import greedy_batches


def build_plan_graph(ctx: GraphContext):  # noqa: ANN201
    """Assemble the LangGraph state machine for planning, batching, estimating, and confirming docstring updates.

    Args:
        ctx: Shared context containing model configuration and the target registry.

    Returns:
        A compiled state graph executable.
    """
    g: StateGraph = StateGraph(PlanState)
    g.add_node("plan", make_plan(ctx))
    g.add_node("batch", make_batch(ctx))
    g.add_node("estimate", make_estimate(ctx))
    g.add_node("confirm", make_confirm(ctx))

    g.add_edge(START, "plan")
    g.add_conditional_edges("plan", lambda s: "batch" if s.get("targets") else END, {"batch": "batch", END: END})
    g.add_edge("batch", "estimate")
    g.add_edge("estimate", "confirm")
    g.add_edge("confirm", END)
    return g.compile()


def batch_targets(ctx: GraphContext, targets: list[TargetRef], offset: int = 0) -> list[BatchRef]:
    """Partition identified targets into token-bound chunks using greedy knapsack bin-packing.

    Args:
        ctx: Context providing token limits and target detail lookups.
        targets: List of references to functions and modules waiting for generation.
        offset: Starting index number for batch identification.

    Returns:
        List of structured batches with unique index IDs.
    """
    if not targets:
        return []

    plan = greedy_batches(targets, size_fn=ctx.registry.token_cost, limit=ctx.batch_token_limit)
    return [BatchRef(id=offset + i, targets=list(b.items)) for i, b in enumerate(plan.batches)]


def make_plan(ctx: GraphContext):  # noqa: ANN201
    """Produce a graph node function that scans paths for undocumented code and caches existing docstring states.

    Args:
        ctx: Context holding the baseline cache stamps and target mapping registry.

    Returns:
        A state graph node function that updates PlanState with targets.
    """

    def plan(state: PlanState) -> PlanState:
        with status("Scanning files..."):
            result = collect_targets(state["paths"], state["repo_root"], ctx.prev_stamps, update=state["flags"].update)
        ctx.registry = TargetRegistry.from_targets(state["repo_root"].resolve(), result.targets, result.file_hashes)
        refs = [TargetRef(rel=t.rel, qualname=t.qualname) for t in result.targets]
        return {"targets": refs, "cache_hits": result.cache_hits}

    return plan


def make_batch(ctx: GraphContext):  # noqa: ANN201
    """Produce a graph node function that aggregates targets into size-bounded batches.

    Args:
        ctx: Context providing token limits and target information.

    Returns:
        A state graph node function that updates PlanState with batch list.
    """

    def batch(state: PlanState) -> PlanState:
        return {"batches": batch_targets(ctx, state["targets"])}

    return batch


def make_estimate(ctx: GraphContext):  # noqa: ANN201
    """Produce a graph node function that estimates token usage and project dollar cost of the run.

    Args:
        ctx: Context containing LLM pricing data and tier configurations.

    Returns:
        A state graph node function that prints a cost summary and records the estimate.
    """

    def estimate(state: PlanState) -> PlanState:
        targets = state["targets"]
        total_input = sum(ctx.registry.token_cost(r) for r in targets)
        per_file_counts: dict[str, int] = defaultdict(int)
        for r in targets:
            per_file_counts[r.rel] += 1
        per_file = sorted(per_file_counts.items())

        info = tier_info(ctx.provider, ctx.tier)
        est = estimate_cost(ctx.provider, ctx.tier, total_input, output_ratio=0.6)

        breakdown = CostBreakdown(
            model=info.model,
            tier=ctx.tier,
            files=len(per_file),
            functions=len(targets),
            input_tokens=est.input_tokens,
            output_tokens=est.output_tokens,
            cost=est.total,
            per_file=per_file,
        )

        console.print(
            cost_panel(
                "Docs run estimate",
                [
                    ("Model", info.model),
                    ("Tier", ctx.tier),
                    ("Files", str(breakdown.files)),
                    ("Functions", str(breakdown.functions)),
                    ("Input tokens", f"~{est.input_tokens:,}"),
                ],
                per_file=breakdown.per_file,
            )
        )
        return {"estimate": breakdown}

    return estimate


def make_confirm(ctx: GraphContext):  # noqa: ANN201
    """Produce a graph node function that prompts the user to approve the planned generation.

    Args:
        ctx: Context containing the prompter and auto-confirm bypass flags.

    Returns:
        A state graph node function that blocks on confirmation and writes approval to state.
    """

    def confirm(state: PlanState) -> PlanState:
        if state.get("confirmed"):
            return {"confirmed": True}
        if state["flags"].update:
            console.print(
                warning_panel(
                    "Full rewrite (--update)",
                    "Every function and module docstring in scope will be regenerated, "
                    "including ones already documented. No hash-diff skip applies — "
                    "the full cost above is billed.",
                )
            )
        if ctx.auto_confirm or ctx.prompter is None:
            return {"confirmed": True}
        answer = ctx.prompter.confirm("Generate docstrings now?")
        if not answer:
            console.print("[dim]Docs run cancelled — nothing written.[/dim]")
        return {"confirmed": bool(answer)}

    return confirm
