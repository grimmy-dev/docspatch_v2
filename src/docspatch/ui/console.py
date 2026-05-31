"""Shared Rich console instances and the status spinner that uses them."""

from collections.abc import Iterator
from contextlib import contextmanager

from rich.console import Console

console = Console()
err_console = Console(stderr=True, style="bold red")

FALLBACK_WIDTH = 80
FALLBACK_HEIGHT = 24


@contextmanager
def status(message: str, spinner: str = "dots") -> Iterator[None]:
    """Show ``message`` with a spinner until the block exits.

    Single source of truth for "working..." indicators on silent operations
    (validate_key, cache scan, etc.) so the terminal never sits idle.
    """
    with console.status(message, spinner=spinner):
        yield


def terminal_size() -> tuple[int, int]:
    """Console ``(width, height)``, with an 80x24 fallback.

    Guards against a virtual terminal that reports 0 or errors on a size query.
    """
    try:
        size = console.size
    except OSError:
        return FALLBACK_WIDTH, FALLBACK_HEIGHT
    width = size.width if size.width > 0 else FALLBACK_WIDTH
    height = size.height if size.height > 0 else FALLBACK_HEIGHT
    return width, height
