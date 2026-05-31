"""Opening the docs checkpoint saver with the right serializer.

Every saver must carry the shared serializer so the custom Pydantic/dataclass
values that travel through graph state are msgpack-allowed; without it langgraph
logs an "unregistered type" warning on every checkpoint read. ``open_checkpoint_saver``
makes that wiring non-optional — a saver cannot be opened here without it.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

# Every custom type that can be checkpointed in graph state, as (module, qualname).
ALLOWED_STATE_TYPES = [
    ("docspatch.schemas", "FunctionMetadata"),
    ("docspatch.pipelines.docs.state", "TargetRef"),
    ("docspatch.pipelines.docs.state", "BatchRef"),
    ("docspatch.pipelines.docs.state", "CostBreakdown"),
    ("docspatch.pipelines.docs.state", "GeneratedDoc"),
    ("docspatch.pipelines.docs.flags", "RunFlags"),
    ("docspatch.pipelines.scout.state", "ScoutBatch"),
    ("docspatch.pipelines.scout.state", "ScoutResult"),
]


def make_serde() -> JsonPlusSerializer:
    """Return the serializer shared by all checkpoint savers."""
    return JsonPlusSerializer(allowed_msgpack_modules=ALLOWED_STATE_TYPES)


def docs_db_path(repo_root: Path) -> Path:
    """Canonical sqlite checkpoint path for a repo (shared by docs, scout, review)."""
    return repo_root / ".docspatch" / "checkpoints" / "docs.sqlite"


@asynccontextmanager
async def open_checkpoint_saver(db_path: Path) -> AsyncIterator[AsyncSqliteSaver]:
    """Open the sqlite checkpointer at ``db_path`` with the shared serializer wired in.

    Creates the parent directory. The serializer is non-optional: a saver opened
    any other way mis-deserializes checkpointed Pydantic state.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as saver:
        saver.serde = make_serde()
        yield saver
