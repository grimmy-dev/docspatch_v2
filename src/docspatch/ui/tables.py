"""Reusable rich Table builder.

Avoids the common layout failures:
- `expand=False` so the table never stretches to break narrow terminals.
- `overflow="fold"` per column so long cells wrap inside instead of clipping.
- Consistent box style and bold header across every command.
"""

from collections.abc import Iterable

from rich import box
from rich.table import Table


def build_table(
    headers: Iterable[str],
    rows: Iterable[Iterable[str]],
    title: str | None = None,
) -> Table:
    """Construct a rich Table with project-standard styling."""
    table = Table(
        title=title,
        box=box.ROUNDED,
        show_header=True,
        header_style="bold",
        expand=False,
        pad_edge=False,
    )
    for header in headers:
        table.add_column(header, no_wrap=False, overflow="fold")
    for row in rows:
        table.add_row(*row)
    return table
