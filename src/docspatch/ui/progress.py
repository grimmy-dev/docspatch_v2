"""Determinate progress bar with status-line updates."""

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
        if message:
            self.bar.update(self.task, description=message)
        self.bar.advance(self.task)

    def set_status(self, text: str) -> None:
        """Update description without advancing — for retry / pause notices."""
        self.bar.update(self.task, description=text)

    def pause(self) -> None:
        """Stop the live render — call before showing a blocking prompt."""
        self.bar.stop()

    def resume(self) -> None:
        """Restart the live render after a prompt completes."""
        self.bar.start()


@contextmanager
def progress_bar(total: int, description: str = "Working") -> Iterator[BarHandle]:
    """Yield a :class:`BarHandle`. ``transient=True`` clears on exit."""
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
