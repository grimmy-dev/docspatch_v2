"""Handle rate limit notifications and user retry feedback."""

from collections.abc import Callable

from docspatch.utils.retry import LLM_RETRY


class RetryDisplay:
    """Per-run retry callback. Pipelines bind a bar sink while active."""

    def __init__(self) -> None:
        """Initialize the display handler."""
        self.sink: Callable[[str], None] | None = None

    def bind(self, sink: Callable[[str], None]) -> None:
        """Send subsequent retry notices to the specified sink.

        Args:
            sink: Output handler for notifications.
        """
        self.sink = sink

    def unbind(self) -> None:
        """Revert to printing to stdout."""
        self.sink = None

    def __call__(self, attempt: int, remaining: float) -> None:
        """Display the rate limit retry information to the user.

        Args:
            attempt: Current retry count.
            remaining: Estimated seconds remaining before the next attempt.
        """
        msg = f"⚠ Rate limited — retry {attempt}/{LLM_RETRY.max_attempts} in {remaining:.0f}s · Ctrl+C to choose"
        if self.sink is not None:
            self.sink(msg)
            return
        print(msg)
