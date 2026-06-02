"""Coordinate the review and commit graph lifecycle for generated documentation."""

import asyncio
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt

from docspatch.pipelines.docs.commit import commit_docstrings
from docspatch.pipelines.docs.context import GraphContext, ReviewHandler
from docspatch.pipelines.docs.generate_graph import generate_for_batch
from docspatch.pipelines.docs.plan_graph import batch_targets
from docspatch.pipelines.docs.state import (
    RERUN_ROUND_CAP,
    BatchRef,
    FinalizeResult,
    GeneratedDoc,
    RegenerateInput,
    ReviewState,
    TargetRef,
)
from docspatch.pipelines.fanout import load_state
from docspatch.source import MODULE_QUALNAME
from docspatch.ui import status


async def drive_finalize(
    ctx: GraphContext,
    saver: AsyncSqliteSaver,
    handler: ReviewHandler | None,
    entries: list[GeneratedDoc],
) -> FinalizeResult:
    """Execute the review and commit graph, relaying interrupts to the UI handler.

    Returns:
        The final summary of processed documentation tasks.

    Raises:
        RuntimeError: The graph interrupts without a provided handler.
    """
    thread_id = f"review-{ctx.run_id}"
    await saver.adelete_thread(thread_id)
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    graph = build_finalize_graph(ctx, saver)

    # Any: graph input is the initial state dict on the first turn, then a
    # Command(resume=...) on every loop after an interrupt — no shared static type.
    next_input: Any = {"entries": entries}
    # Bridge the gap after the progress bar clears: the first invocation reads
    # state and builds the review queue before it interrupts. Only the first —
    # an interactive run always stops at the review interrupt before reaching
    # commit, so commit's own status spinner never nests inside this one.
    bridging = handler is not None
    while True:
        if bridging:
            with status("Preparing review..."):
                result = await graph.ainvoke(next_input, config=config)
            bridging = False
        else:
            result = await graph.ainvoke(next_input, config=config)
        interrupts = result.get("__interrupt__")
        if not interrupts:
            break
        if handler is None:
            raise RuntimeError("graph raised an interrupt but no review handler was supplied")
        choice = await asyncio.to_thread(handler, interrupts[0].value)
        next_input = Command(resume=choice)

    final = await load_state(saver, config)
    await saver.adelete_thread(thread_id)
    if final.get("aborted"):
        return FinalizeResult(committed=[], skipped=[], fn_count=0, aborted=True)

    committed = final.get("committed_files", [])
    accepted = set(final.get("accepted", []))
    written = [e for e in final.get("entries", []) if e.rel in committed and f"{e.rel}::{e.qualname}" in accepted]
    module_count = sum(1 for e in written if e.qualname == MODULE_QUALNAME)
    return FinalizeResult(
        committed=committed,
        skipped=final.get("skipped_files", []),
        fn_count=len(written) - module_count,
        module_count=module_count,
        error=final.get("commit_error"),
    )


def build_finalize_graph(ctx: GraphContext, saver: AsyncSqliteSaver):  # noqa: ANN201
    """Define the state transition graph for reviewing and committing changes.

    Returns:
        The compiled StateGraph.
    """
    g: StateGraph = StateGraph(ReviewState)
    g.add_node("review", make_review(ctx))
    g.add_node("regenerate", make_regenerate(ctx))
    g.add_node("commit", make_commit(ctx))
    g.add_edge(START, "review")
    g.add_conditional_edges("review", route_after_review, ["regenerate", "commit", END])
    g.add_edge("regenerate", "review")
    g.add_edge("commit", END)
    return g.compile(checkpointer=saver)


def route_after_review(state: ReviewState) -> list[Send] | str:
    """Direct state transitions based on the user's review outcome.

    Returns:
        The target node or list of fan-out sends.
    """
    if state.get("aborted"):
        return END
    batches = state.get("pending_rerun", [])
    if not batches:
        return "commit"
    feedback = state.get("feedback", {})
    return [Send("regenerate", {"batch": b, "feedback": feedback}) for b in batches]


def make_review(ctx: GraphContext):  # noqa: ANN201
    """Create an interrupt node for user evaluation of generated content.

    Returns:
        A function compatible with state graph node signature.
    """

    def review(state: ReviewState) -> ReviewState:
        entries = state.get("entries", [])
        accepted = list(state.get("accepted", []))
        rejected = list(state.get("rejected", []))
        round_n = state.get("review_round", 0)

        decided = set(accepted) | set(rejected)
        pending = [e for e in entries if f"{e.rel}::{e.qualname}" not in decided]
        if not pending:
            return {"review_round": round_n + 1, "pending_rerun": []}

        if not ctx.interactive:
            # Auto-accept clean docstrings; auto-reject parse-failed ones —
            # they carry no docstring and must never be committed.
            accepted.extend(f"{e.rel}::{e.qualname}" for e in pending if not e.parse_failed)
            rejected.extend(f"{e.rel}::{e.qualname}" for e in pending if e.parse_failed)
            return {
                "accepted": accepted,
                "rejected": rejected,
                "review_round": round_n + 1,
                "pending_rerun": [],
            }

        allow_rerun = round_n < RERUN_ROUND_CAP
        choice = interrupt(
            {
                "type": "review",
                "entries": [e.model_dump() for e in pending],
                "round": round_n,
                "allow_rerun": allow_rerun,
            }
        )
        if choice.get("aborted"):
            return {"aborted": True, "pending_rerun": []}

        accepted.extend(choice.get("accepted", []))
        rejected.extend(choice.get("rejected", []))
        rerun_ids: list[str] = choice.get("rerun", []) if allow_rerun else []
        notes: dict[str, str] = choice.get("feedback", {})

        result: ReviewState = {
            "accepted": accepted,
            "rejected": rejected,
            "review_round": round_n + 1,
            "feedback": {rid: [notes[rid]] for rid in rerun_ids if notes.get(rid)},
            "pending_rerun": rerun_batches(ctx, rerun_ids),
        }
        # Hand-edited docstrings overwrite their generated entries (merge_generated
        # keys by (rel, qualname)), so commit writes the user's text.
        if edits := choice.get("edited", {}):
            by_id = {f"{e.rel}::{e.qualname}": e for e in pending}
            result["entries"] = [
                by_id[rid].model_copy(update={"docstring": text}) for rid, text in edits.items() if rid in by_id
            ]
        return result

    return review


def rerun_batches(ctx: GraphContext, rerun_ids: list[str]) -> list[BatchRef]:
    """Organize rerun targets into batches based on token constraints.

    Returns:
        A list of BatchRef instances.
    """
    refs = [
        TargetRef(rel=rel, qualname=qualname)
        for rid in rerun_ids
        for rel, _, qualname in [rid.partition("::")]
        if (rel, qualname) in ctx.full_targets
    ]
    return batch_targets(ctx, refs)


def make_regenerate(ctx: GraphContext):  # noqa: ANN201
    """Construct a regeneration handler to update docstrings based on batch feedback.

    Args:
        ctx: Context managing the documentation graph.

    Returns:
        An asynchronous callable that accepts a payload and returns the resulting ReviewState.
    """

    async def regenerate(state: RegenerateInput) -> ReviewState:
        docs = await generate_for_batch(ctx, state["batch"], state.get("feedback", {}))
        return {"entries": docs or []}

    return regenerate


def make_commit(ctx: GraphContext):  # noqa: ANN201
    """Create a commit operation to persist accepted docstrings to disk.

    Args:
        ctx: Context providing the graph structure for the commit process.

    Returns:
        A callable that takes a ReviewState and returns the updated state after committing changes.
    """

    def commit(state: ReviewState) -> ReviewState:
        return cast("ReviewState", commit_docstrings(ctx, dict(state)))

    return commit
