"""Shared Rich console instances."""

from rich.console import Console

console = Console()
err_console = Console(stderr=True, style="bold red")

FALLBACK_WIDTH = 80
FALLBACK_HEIGHT = 24


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
