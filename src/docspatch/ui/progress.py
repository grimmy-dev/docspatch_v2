"""Step-progress handle that reports counts on the shared command timer line."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from docspatch.ui.console import StatusHandle, timed_status


@dataclass
class BarHandle:
    """Reports ``description N/total`` on the active timer line.

    ``bar(msg)`` advances the count (and optionally retitles); ``set_status``
    changes the text without advancing.
    """

    handle: StatusHandle
    total: int
    description: str
    completed: int = 0

    def __call__(self, message: str | None = None) -> None:
        """Advance the count by one and optionally replace the description.

        Args:
            message: An optional new description.
        """
        if message:
            self.description = message
        self.completed += 1
        self._render()

    def set_status(self, text: str) -> None:
        """Replace the description text without advancing the count.

        Args:
            text: The new description text.
        """
        self.description = text
        self._render()

    def _render(self) -> None:
        """Write the current ``description N/total`` to the timer line."""
        self.handle.update(f"{self.description} {self.completed}/{self.total}")

    def pause(self) -> None:
        """Stop the live line so a prompt can own the terminal."""
        self.handle.progress.stop()

    def resume(self) -> None:
        """Resume the live line after a prompt."""
        self.handle.progress.start()


@contextmanager
def progress_bar(total: int, description: str = "Working") -> Iterator[BarHandle]:
    """Track step progress as a count on the shared command timer line.

    Args:
        total: The total number of steps in the task.
        description: The title shown ahead of the count.

    Returns:
        An iterator yielding a BarHandle.
    """
    with timed_status(f"{description} 0/{total}") as handle:
        yield BarHandle(handle=handle, total=total, description=description)
