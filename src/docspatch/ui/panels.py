"""Key/value summary panels — used for cost estimates, scout results, etc."""

from collections.abc import Iterable

from rich.console import Group
from rich.panel import Panel
from rich.text import Text


def kv_panel(title: str, items: Iterable[tuple[str, str]], border_style: str = "cyan") -> Panel:
    """Render a key/value panel with aligned keys."""
    rows = list(items)
    key_width = max((len(k) for k, _ in rows), default=0)
    lines = [Text.assemble((f"{k:<{key_width}}  ", "dim"), v) for k, v in rows]
    return Panel(Group(*lines), title=title, expand=False, border_style=border_style)
