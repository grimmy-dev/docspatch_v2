"""Exposes the lazy-loaded run_docs entry point for docstring generation."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docspatch.pipelines.docs.pipeline import run_docs

__all__ = ["run_docs"]


def __getattr__(name: str) -> object:
    """Load and return the run_docs pipeline entry point dynamically on first attribute access.

    Args:
        name: The attribute being accessed.

    Returns:
        The run_docs entry point.

    Raises:
        AttributeError: The name is not a public export.
    """
    if name == "run_docs":
        from docspatch.pipelines.docs.pipeline import run_docs

        return run_docs
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
