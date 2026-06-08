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


# A single persistent timer owns the bottom line for the whole command. While
# it is active, status/timed_status retitle it rather than opening their own
# spinner, so the elapsed counter keeps ticking across steps and printed output
# scrolls above it. QuestionaryPrompter suspends it around prompts so questionary
# owns the terminal cleanly. None of this engages in tests or when piped — the
# functions fall back to a per-call transient spinner.
_timer: Progress | None = None
_timer_task: TaskID | None = None
_timer_stack: list[str] = []
_TIMER_IDLE = "Working…"


def _spinner_columns(spinner: str = "dots") -> tuple[ProgressColumn, ...]:
    """Build the spinner-message-elapsed columns shared by every spinner."""
    return (SpinnerColumn(spinner_name=spinner), TextColumn("[bold]{task.description}"), CommandClockColumn())


@contextmanager
def command_timer() -> Iterator[None]:
    """Run one persistent elapsed counter for the length of a command.

    The counter keeps ticking between steps while printed output scrolls above
    it. A no-op when a timer is already running or stdout is not a terminal.
    """
    global _timer, _timer_task
    if _timer is not None or not console.is_terminal:
        yield
        return
    progress = Progress(*_spinner_columns(), console=console, transient=True)
    progress.start()
    _timer, _timer_task = progress, progress.add_task(_TIMER_IDLE, total=None)
    try:
        yield
    finally:
        progress.stop()
        _timer, _timer_task = None, None
        _timer_stack.clear()


@contextmanager
def suspend_timer() -> Iterator[None]:
    """Pause the persistent timer so a prompt can own the terminal."""
    if _timer is None:
        yield
        return
    _timer.stop()
    try:
        yield
    finally:
        if _timer is not None:
            _timer.start()


@contextmanager
def timed_status(message: str, spinner: str = "dots") -> Iterator[StatusHandle]:
    """Show a spinner with a live elapsed timer for a long-running step.

    When a command timer is active this retitles the shared bottom line;
    otherwise it opens its own transient spinner.

    Args:
        message: The status message to show.
        spinner: The spinner style name.

    Returns:
        A handle whose ``update`` swaps the message as substeps progress.
    """
    if _timer is not None and _timer_task is not None:
        _timer_stack.append(message)
        _timer.update(_timer_task, description=message)
        try:
            yield StatusHandle(_timer, _timer_task)
        finally:
            _timer_stack.pop()
            _timer.update(_timer_task, description=_timer_stack[-1] if _timer_stack else _TIMER_IDLE)
        return
    with Progress(*_spinner_columns(spinner), console=console, transient=True) as progress:
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
