"""Executes parallel workflows using LangGraph to process structured batches."""

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
    """Construct a routing function that fans out uncompleted batches to a target node via Send operations.

    Args:
        node_name: Name of the target state graph node to receive the sends.
        payload_fn: Callable that constructs the payload for a single batch from the overall state.

    Returns:
        A routing function that takes the current state and returns a list of Send commands or END.
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
    """Compile a state graph configured to process batches in parallel with checkpoints.

    Args:
        state_type: The typed dictionary or class defining the graph state schema.
        node_name: The processing node identifier.
        node: The async callable representing the processing action.
        payload_fn: The logic that maps state data to parallel batch payloads.
        saver: The SQLite checkpoint manager used to persist state.

    Returns:
        The compiled runnable graph.
    """
    g: StateGraph = StateGraph(state_type)
    g.add_node(node_name, node)
    g.add_conditional_edges(START, make_router(node_name, payload_fn), [node_name, END])
    g.add_edge(node_name, END)
    return g.compile(checkpointer=saver)


async def load_state(saver: AsyncSqliteSaver, config: RunnableConfig) -> dict[str, Any]:
    """Fetch the most recent state checkpoint dictionary from the state checkpointer.

    Args:
        saver: The SQLite checkpointer holding execution records.
        config: The runnable configuration containing the target thread identifier.

    Returns:
        The state channel values at the latest checkpoint, or empty.
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
    """Execute batched tasks in waves, returning final states or swapping resources upon exhaustion.

    Args:
        graph: The compiled parallel state graph to execute.
        saver: The persistent checkpointer saving wave progress.
        config: The execution context mapping thread history.
        initial: The initial state inputs to load into the first graph invocation.
        pending: A sequence of unresolved batch items needing execution.
        switch: An async trigger to substitute exhausted API keys or backends.
        label: The descriptive label of the process for error reporting.
        on_wave: An optional callback triggered after completing a cycle of parallel nodes.

    Returns:
        The consolidated final execution state.

    Raises:
        TransientExhausted: All processing attempts fail and no switch callback is provided or successful.
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
