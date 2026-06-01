"""Initialize standard console and error streams with Rich utilities."""

from collections.abc import Iterator
from contextlib import contextmanager

from rich.console import Console

console = Console()
err_console = Console(stderr=True, style="bold red")

FALLBACK_WIDTH = 80
FALLBACK_HEIGHT = 24


@contextmanager
def status(message: str, spinner: str = "dots") -> Iterator[None]:
    """Display a working spinner for the duration of a code block."""
    with console.status(message, spinner=spinner):
        yield


def terminal_size() -> tuple[int, int]:
    """Retrieve the current terminal dimensions with sensible fallbacks.

    Returns:
        A tuple of width and height.
    """
    try:
        size = console.size
    except OSError:
        return FALLBACK_WIDTH, FALLBACK_HEIGHT
    width = size.width if size.width > 0 else FALLBACK_WIDTH
    height = size.height if size.height > 0 else FALLBACK_HEIGHT
    return width, height
