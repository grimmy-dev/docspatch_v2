"""Support distributed parallel execution via graph state.
This module defines primitives for routing tasks and managing fan-out workflow life cycles."""

from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Protocol

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from docspatch.utils.errors import TransientExhausted


class HasId(Protocol):
    """A batch tracked by its int ``id`` in the ``completed_batches`` channel."""

    id: int


PayloadFn = Callable[[dict[str, Any], Any], dict[str, Any]]
"""Build the Send payload for one batch from the live state and the batch."""

SwitchFn = Callable[[], Awaitable[bool]]
"""Swap the exhausted client and assign it back. True to continue, False to abort."""


def make_router(node_name: str, payload_fn: PayloadFn) -> Callable[[dict[str, Any]], list[Send] | str]:
    """Build a routing function for conditional node invocation.

    Args:
        node_name: Name of the target processing node.
        payload_fn: Callable to construct node input from state.

    Returns:
        Routing logic for the state graph.
    """

    def route(state: dict[str, Any]) -> list[Send] | str:
        completed = set(state.get("completed_batches", []))
        sends = [Send(node_name, payload_fn(state, batch)) for batch in state.get("batches", []) if batch.id not in completed]
        return sends or END

    return route


def build_fanout_graph(
    state_type: type,
    node_name: str,
    node: Callable[..., Awaitable[dict[str, Any]]],
    payload_fn: PayloadFn,
    saver: AsyncSqliteSaver,
) -> Any:  # noqa: ANN401 — langgraph's compiled graph type is not publicly nameable
    """Compile a state graph for parallel batch processing.

    Args:
        node_name: Target processing node identifier.
        node: Async function for processing batches.
        payload_fn: Logic to prepare batch data.
        saver: Checkpointer for persisting execution state.

    Returns:
        Compiled graph instance.
    """
    g: StateGraph = StateGraph(state_type)
    g.add_node(node_name, node)
    g.add_conditional_edges(START, make_router(node_name, payload_fn), [node_name, END])
    g.add_edge(node_name, END)
    return g.compile(checkpointer=saver)


async def load_state(saver: AsyncSqliteSaver, config: RunnableConfig) -> dict[str, Any]:
    """Fetch the last committed state from a checkpointer.

    Args:
        saver: Async checkpointer instance.
        config: Runnable configuration including thread identifier.

    Returns:
        Current state dictionary.
    """
    snap = await saver.aget_tuple(config)
    if snap is None or snap.checkpoint is None:
        return {}
    return dict(snap.checkpoint.get("channel_values", {}))


async def run_fanout[B: HasId](
    graph: Any,  # noqa: ANN401 — compiled langgraph, see build_fanout_graph
    saver: AsyncSqliteSaver,
    config: RunnableConfig,
    initial: dict[str, Any],
    pending: Sequence[B],
    switch: SwitchFn | None,
    label: str,
    on_wave: Callable[[int, dict[str, Any], Sequence[B]], None] | None = None,
) -> dict[str, Any]:
    """Execute batches in waves until completion or exhaustion.

    Args:
        graph: The compiled state graph.
        pending: Sequenced batches awaiting processing.
        switch: Handler for swapping exhausted resources.

    Returns:
        The final aggregate state.
    """
    state = dict(initial)
    wave = 0
    while True:
        await graph.ainvoke(state, config=config)
        current = await load_state(saver, config)
        done = set(current.get("completed_batches", []))
        next_pending = [b for b in pending if b.id not in done]
        if not next_pending:
            return current
        if switch is None:
            raise TransientExhausted.after(0, RuntimeError(f"{label} exhausted, no switch handler"))
        if not await switch():
            return current
        pending = next_pending
        wave += 1
        if on_wave is not None:
            on_wave(wave, current, pending)
        state = {"batches": pending}
