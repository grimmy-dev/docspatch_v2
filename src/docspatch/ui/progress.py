"""Defines custom progress bars and task handles powered by the Rich progress module."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from rich.progress import BarColumn, Progress, SpinnerColumn, TaskID, TextColumn, TimeElapsedColumn

from docspatch.ui.console import console


@dataclass
class BarHandle:
    """Callable handle: ``bar(msg)`` advances, ``bar.set_status(msg)`` updates description only."""

    bar: Progress
    task: TaskID

    def __call__(self, message: str | None = None) -> None:
        """Advance the task progress and optionally update its description message.

        Args:
            message: An optional status description update.
        """
        if message:
            self.bar.update(self.task, description=message)
        self.bar.advance(self.task)

    def set_status(self, text: str) -> None:
        """Update the progress task description without advancing the progress count.

        Args:
            text: The new description text.
        """
        self.bar.update(self.task, description=text)

    def pause(self) -> None:
        """Stop the progress bar display rendering."""
        self.bar.stop()

    def resume(self) -> None:
        """Resume the progress bar display rendering."""
        self.bar.start()


@contextmanager
def progress_bar(total: int, description: str = "Working") -> Iterator[BarHandle]:
    """Initialize a transient progress bar context manager.

    Args:
        total: The total number of steps in the task.
        description: The title description of the progress task.

    Returns:
        An iterator yielding a BarHandle.
    """
    columns = (
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
    )
    with Progress(*columns, console=console, transient=True) as progress:
        task_id = progress.add_task(description, total=total)
        yield BarHandle(bar=progress, task=task_id)
