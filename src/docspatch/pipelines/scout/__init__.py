"""Export the primary scouting interface.

``run_scout`` pulls langgraph + the provider SDKs, so it is exposed lazily: a
light import of a sibling module does not drag the whole pipeline in.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docspatch.pipelines.scout.graph import run_scout

__all__ = ["run_scout"]


def __getattr__(name: str) -> object:
    """Load ``run_scout`` from the graph module on first access.

    Args:
        name: The attribute being accessed.

    Returns:
        The ``run_scout`` entry point.

    Raises:
        AttributeError: The name is not a public export.
    """
    if name == "run_scout":
        from docspatch.pipelines.scout.graph import run_scout

        return run_scout
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
