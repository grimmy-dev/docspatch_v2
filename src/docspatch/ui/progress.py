"""Determinate progress bar — used when total work units are known upfront.

Yields an `advance(message=None)` callable so callers do not import rich
directly. Nodes / pipelines invoke `advance` once per completed unit.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from docspatch.ui.console import console

Advance = Callable[[str | None], None]


@contextmanager
def progress_bar(total: int, description: str = "Working") -> Iterator[Advance]:
    """Context manager yielding an `advance(message)` callable.

    `transient=True` clears the bar on exit so terminal scrollback stays clean.
    """
    columns = (
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
    )
    with Progress(*columns, console=console, transient=True) as bar:
        task_id = bar.add_task(description, total=total)

        def advance(message: str | None = None) -> None:
            if message:
                bar.update(task_id, description=message)
            bar.advance(task_id)

        yield advance
