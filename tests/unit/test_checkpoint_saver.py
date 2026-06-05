"""open_checkpoint_saver wires the serializer so checkpointed Pydantic state round-trips.

The serializer is the whole point of the opener: without it langgraph warns on every
read and custom types fail to msgpack. This proves a value written through the opener
comes back intact from a freshly reopened saver.
"""

import asyncio
from operator import add
from pathlib import Path
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from docspatch.checkpoints.saver import docs_db_path, open_checkpoint_saver
from docspatch.pipelines.docs.state import GeneratedDoc


def test_docs_db_path_is_canonical(tmp_path: Path) -> None:
    assert docs_db_path(tmp_path) == tmp_path / ".docspatch" / "checkpoints" / "docs.sqlite"


def test_opener_creates_parent_dir(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "checkpoints" / "docs.sqlite"

    async def go() -> None:
        async with open_checkpoint_saver(db_path):
            pass

    asyncio.run(go())
    assert db_path.parent.is_dir()


class _State(TypedDict, total=False):
    docs: Annotated[list[GeneratedDoc], add]


def test_pydantic_state_round_trips_through_reopened_saver(tmp_path: Path) -> None:
    """A GeneratedDoc checkpointed under the opener reloads intact from a new saver."""
    db_path = docs_db_path(tmp_path)
    config = {"configurable": {"thread_id": "run-1"}}
    doc = GeneratedDoc(rel="a.py", qualname="f", docstring="hi")

    async def write() -> None:
        async with open_checkpoint_saver(db_path) as saver:
            g: StateGraph = StateGraph(_State)
            g.add_node("emit", lambda _s: {"docs": [doc]})
            g.add_edge(START, "emit")
            g.add_edge("emit", END)
            await g.compile(checkpointer=saver).ainvoke({}, config=config)

    async def read() -> GeneratedDoc:
        async with open_checkpoint_saver(db_path) as saver:
            snap = await saver.aget_tuple(config)
            assert snap is not None and snap.checkpoint is not None
            return snap.checkpoint["channel_values"]["docs"][0]

    asyncio.run(write())
    reloaded = asyncio.run(read())
    assert reloaded == doc
    assert isinstance(reloaded, GeneratedDoc)
