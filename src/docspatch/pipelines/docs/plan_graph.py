"""Define the state machine workflow for planning and batching documentation tasks."""

from collections import defaultdict

from langgraph.graph import END, START, StateGraph

from docspatch.llm.catalogue import tier_info
from docspatch.llm.pricing import estimate_cost
from docspatch.pipelines.docs.context import GraphContext
from docspatch.pipelines.docs.planner import collect_targets
from docspatch.pipelines.docs.state import BatchRef, CostBreakdown, PlanState, TargetRef
from docspatch.ui import console, cost_panel, status, warning_panel
from docspatch.utils.batcher import greedy_batches


def build_plan_graph(ctx: GraphContext):  # noqa: ANN201
    """Construct the state machine for planning, batching, estimating, and confirming documentation tasks.

    Args:
        ctx: Context containing repository and generation settings.

    Returns:
        The compiled state machine graph.
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
    """Partition targets into batches based on token costs, starting batch indexing from a given offset.

    Args:
        ctx: The context holding full target definitions.
        targets: List of target functions to distribute.
        offset: Initial ID for the first batch.

    Returns:
        A list of structured batch objects.
    """
    if not targets:
        return []

    def size(ref: TargetRef) -> int:
        return ctx.full_targets[(ref.rel, ref.qualname)].token_cost

    plan = greedy_batches(targets, size_fn=size, limit=ctx.batch_token_limit)
    return [BatchRef(id=offset + i, targets=list(b.items)) for i, b in enumerate(plan.batches)]


def make_plan(ctx: GraphContext):  # noqa: ANN201
    """Scan files to identify functions needing documentation and prepare the target lookup table.

    Args:
        ctx: Context maintaining the target registry.

    Returns:
        The planning node function.
    """

    def plan(state: PlanState) -> PlanState:
        with status("Scanning files..."):
            result = collect_targets(state["paths"], state["repo_root"], cache=ctx.cache, update=state["flags"].update)
        ctx.full_targets = {(t.rel, t.qualname): t for t in result.targets}
        refs = [TargetRef(rel=t.rel, qualname=t.qualname) for t in result.targets]
        return {"targets": refs, "cache_hits": result.cache_hits}

    return plan


def make_batch(ctx: GraphContext):  # noqa: ANN201
    """Organize identified targets into optimal generation batches.

    Args:
        ctx: Context providing token limits and target information.

    Returns:
        The batching node function.
    """

    def batch(state: PlanState) -> PlanState:
        return {"batches": batch_targets(ctx, state["targets"])}

    return batch


def make_estimate(ctx: GraphContext):  # noqa: ANN201
    """Calculate and display the projected token usage and costs for the generated documentation run.

    Args:
        ctx: Context holding pricing and model configuration.

    Returns:
        The estimation node function.
    """

    def estimate(state: PlanState) -> PlanState:
        targets = state["targets"]
        total_input = sum(ctx.full_targets[(r.rel, r.qualname)].token_cost for r in targets)
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
                    ("Output tokens", f"~{est.output_tokens:,} (projected)"),
                    ("Cost", f"~${est.total:.4f}  (in ${est.input_cost:.4f} + out ${est.output_cost:.4f})"),
                ],
                per_file=breakdown.per_file,
            )
        )
        return {"estimate": breakdown}

    return estimate


def make_confirm(ctx: GraphContext):  # noqa: ANN201
    """Prompt the user for approval to proceed with generation, unless explicitly bypassed or resuming an existing run.

    Args:
        ctx: Context providing interaction and automation flags.

    Returns:
        The confirmation node function.
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
