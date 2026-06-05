"""Asynchronous SQLite-backed checkpoint state saver setup."""

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
]


def make_serde() -> JsonPlusSerializer:
    """Construct the serializer used for checkpoint objects.

    Returns:
        JsonPlusSerializer instance.
    """
    return JsonPlusSerializer(allowed_msgpack_modules=ALLOWED_STATE_TYPES)


def docs_db_path(repo_root: Path) -> Path:
    """Get the filesystem path for the shared SQLite checkpoint store.

    Args:
        repo_root: Repository base directory.

    Returns:
        Database path.
    """
    return repo_root / ".docspatch" / "checkpoints" / "docs.sqlite"


@asynccontextmanager
async def open_checkpoint_saver(db_path: Path) -> AsyncIterator[AsyncSqliteSaver]:
    """Open the SQLite checkpoint store as an asynchronous resource.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        An async iterator for the saver instance.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as saver:
        saver.serde = make_serde()
        yield saver
