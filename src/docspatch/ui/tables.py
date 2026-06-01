"""Provide utilities for generating standard UI tables."""

from collections.abc import Iterable

from rich import box
from rich.table import Table


def build_table(
    headers: Iterable[str],
    rows: Iterable[Iterable[str]],
    title: str | None = None,
) -> Table:
    """Assemble a table with standardized project styling.

    Args:
        headers: Table column labels.
        rows: Table row data.

    Returns:
        Table object.
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
