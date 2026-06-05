"""Constructs and formats console tables with standardized layout settings."""

from collections.abc import Iterable

from rich import box
from rich.table import Table


def build_table(
    headers: Iterable[str],
    rows: Iterable[Iterable[str]],
    title: str | None = None,
) -> Table:
    """Create a styled Rich table using predefined rounded borders and column wrapping.

    Args:
        headers: Text labels for the table columns.
        rows: Matrix of row data strings to populate.
        title: Optional header text displayed above the table.

    Returns:
        A configured Rich table instance ready for console rendering.
    """
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
