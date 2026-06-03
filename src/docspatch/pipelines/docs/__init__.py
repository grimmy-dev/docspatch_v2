"""Define the public interface for the documentation pipeline.

``run_docs`` pulls langgraph + the provider SDKs, so it is exposed lazily: a
light import of a sibling module (e.g. ``flags`` for ``RunFlags``) does not drag
the whole pipeline in.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docspatch.pipelines.docs.pipeline import run_docs

__all__ = ["run_docs"]


def __getattr__(name: str) -> object:
    """Load ``run_docs`` from the pipeline module on first access.

    Args:
        name: The attribute being accessed.

    Returns:
        The ``run_docs`` entry point.

    Raises:
        AttributeError: The name is not a public export.
    """
    if name == "run_docs":
        from docspatch.pipelines.docs.pipeline import run_docs

        return run_docs
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
