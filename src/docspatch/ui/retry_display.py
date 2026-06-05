"""RetryDisplay: format rate-limit retry/backoff notices to a sink."""

from collections.abc import Callable

from docspatch.utils.retry import LLM_RETRY


class RetryDisplay:
    """Per-run retry callback. Pipelines bind a bar sink while active."""

    def __init__(self) -> None:
        """Set up an empty output callback sink."""
        self.sink: Callable[[str], None] | None = None

    def bind(self, sink: Callable[[str], None]) -> None:
        """Assign a callback sink to receive retry messages instead of printing to stdout.

        Args:
            sink: Output handler for notifications.
        """
        self.sink = sink

    def unbind(self) -> None:
        """Clear the assigned callback sink to resume printing messages directly to stdout."""
        self.sink = None

    def __call__(self, attempt: int, remaining: float) -> None:
        """Format and output the current backoff attempt and remaining delay to the configured sink or stdout.

        Args:
            attempt: Current retry count.
            remaining: Estimated seconds remaining before the next attempt.
        """
        msg = f"⚠ Rate limited — retry {attempt}/{LLM_RETRY.max_attempts} in {remaining:.0f}s · Ctrl+C to choose"
        if self.sink is not None:
            self.sink(msg)
            return
        print(msg)
