"""Defines global Rich consoles and terminal measurement utilities."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from rich.console import Console
from rich.progress import Progress, ProgressColumn, SpinnerColumn, Task, TaskID, TextColumn
from rich.text import Text

from docspatch.utils.timing import clock, format_duration

console = Console()
err_console = Console(stderr=True, style="bold red")

FALLBACK_WIDTH = 80
FALLBACK_HEIGHT = 24


class CommandClockColumn(ProgressColumn):
    """Render cumulative command time, so every spinner and bar shares one timer."""

    def render(self, task: Task) -> Text:
        """Return the command's wall-clock elapsed as dim text.

        Args:
            task: The progress task (unused; the clock is process-wide).

        Returns:
            The formatted elapsed time.
        """
        return Text(format_duration(clock.wall_elapsed()), style="dim")


@dataclass
class StatusHandle:
    """Live spinner handle: ``handle.update(msg)`` swaps the message in place."""

    progress: Progress
    task: TaskID

    def update(self, message: str) -> None:
        """Replace the spinner message without resetting the elapsed timer.

        Args:
            message: The new status message.
        """
        self.progress.update(self.task, description=message)


@contextmanager
def timed_status(message: str, spinner: str = "dots") -> Iterator[StatusHandle]:
    """Show a spinner with a live elapsed timer for a long-running step.

    Args:
        message: The status message to show.
        spinner: The spinner style name.

    Returns:
        A handle whose ``update`` swaps the message as substeps progress.
    """
    columns = (SpinnerColumn(spinner_name=spinner), TextColumn("[bold]{task.description}"), CommandClockColumn())
    with Progress(*columns, console=console, transient=True) as progress:
        task = progress.add_task(message, total=None)
        yield StatusHandle(progress, task)


@contextmanager
def status(message: str, spinner: str = "dots") -> Iterator[None]:
    """Display a working status spinner with a live elapsed timer.

    Args:
        message: The status message to show.
        spinner: The spinner style name.
    """
    with timed_status(message, spinner):
        yield


def terminal_size() -> tuple[int, int]:
    """Retrieve the current terminal dimensions with fallbacks.

    Returns:
        A tuple containing the terminal width and height.
    """
    try:
        size = console.size
    except OSError:
        return FALLBACK_WIDTH, FALLBACK_HEIGHT
    width = size.width if size.width > 0 else FALLBACK_WIDTH
    height = size.height if size.height > 0 else FALLBACK_HEIGHT
    return width, height
