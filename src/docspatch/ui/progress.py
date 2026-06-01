"""Enable interactive progress bars for long-running operations."""

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
        """Advance the progress bar or update its description."""
        if message:
            self.bar.update(self.task, description=message)
        self.bar.advance(self.task)

    def set_status(self, text: str) -> None:
        """Update the progress description without advancing progress."""
        self.bar.update(self.task, description=text)

    def pause(self) -> None:
        """Stop the live progress bar output."""
        self.bar.stop()

    def resume(self) -> None:
        """Restart the live progress bar output."""
        self.bar.start()


@contextmanager
def progress_bar(total: int, description: str = "Working") -> Iterator[BarHandle]:
    """Initialize a context-managed progress bar.

    Returns:
        A handle to control the progress bar.
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
