"""Provide panel templates for displaying metrics and warnings."""

from collections.abc import Iterable

from rich.console import Group
from rich.panel import Panel
from rich.text import Text


def kv_panel(title: str, items: Iterable[tuple[str, str]], border_style: str = "cyan") -> Panel:
    """Render a bordered panel containing key-value pairs.

    Returns:
        The rendered Rich panel.
    """
    rows = list(items)
    key_width = max((len(k) for k, _ in rows), default=0)
    lines = [Text.assemble((f"{k:<{key_width}}  ", "dim"), v) for k, v in rows]
    return Panel(Group(*lines), title=title, expand=False, border_style=border_style)


def warning_panel(title: str, message: str) -> Panel:
    """Render a yellow-bordered warning panel.

    Returns:
        The rendered warning panel.
    """
    return Panel(Text(message), title=title, expand=False, border_style="yellow")


def cost_panel(
    title: str,
    rows: Iterable[tuple[str, str]],
    per_file: Iterable[tuple[str, int]] | None = None,
    border_style: str = "cyan",
) -> Panel:
    """Render a summary panel with cost metrics and per-file counts.

    Returns:
        The rendered cost panel.
    """
    kv = list(rows)
    width = max((len(k) for k, _ in kv), default=0)
    top = [Text.assemble((f"{k:<{width}}  ", "dim"), v) for k, v in kv]

    if not per_file:
        return Panel(Group(*top), title=title, expand=False, border_style=border_style)

    files = list(per_file)
    name_width = max((len(p) for p, _ in files), default=0)
    sep = Text("─" * (width + max(name_width, 12) + 8), style="dim")
    header = Text("Files", style="bold")
    file_lines = [
        Text.assemble((f"  {rel:<{name_width}}  ", ""), (f"{count} fn{'s' if count != 1 else ''}", "dim")) for rel, count in files
    ]
    body = Group(*top, sep, header, *file_lines)
    return Panel(body, title=title, expand=False, border_style=border_style)
