"""Route retry status messages to the active progress bar or stdout."""

from collections.abc import Callable

from docspatch.llm.client import LLM_RETRY


class RetryDisplay:
    """Per-run retry callback. Pipelines bind a bar sink while active."""

    def __init__(self) -> None:
        self.sink: Callable[[str], None] | None = None

    def bind(self, sink: Callable[[str], None]) -> None:
        """Send subsequent retry notices to ``sink`` (e.g., progress bar description)."""
        self.sink = sink

    def unbind(self) -> None:
        """Revert to printing to stdout."""
        self.sink = None

    def __call__(self, attempt: int, remaining: float) -> None:
        msg = (
            f"⚠ Rate limited — retry {attempt}/{LLM_RETRY.max_attempts} "
            f"in {remaining:.0f}s · Ctrl+C to choose"
        )
        if self.sink is not None:
            self.sink(msg)
            return
        print(msg)
