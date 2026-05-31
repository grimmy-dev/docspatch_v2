"""Shared LangGraph checkpoint serializer.

Built once and set on every saver so the custom Pydantic/dataclass values that
travel through graph state are msgpack-allowed — without it langgraph logs an
"unregistered type" warning on every checkpoint read.
"""

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

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
