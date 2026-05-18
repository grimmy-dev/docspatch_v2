"""Status spinner — single source of truth for "working..." indicators.

Use for silent operations (validate_key, cache scan, etc.) so the terminal
never sits idle without feedback.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from docspatch.ui.console import console


@contextmanager
def status(message: str, spinner: str = "dots") -> Iterator[None]:
    """Show `message` with a spinner until the block exits."""
    with console.status(message, spinner=spinner):
        yield
