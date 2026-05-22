"""Coordinated backoff across concurrent calls. One shared timer per gate."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

OnRetry = Callable[[int, float], None]
IsRetriable = Callable[[Exception], bool]


@dataclass(frozen=True)
class RetryPolicy:
    """Exponential backoff with cap. ``delay = min(base_delay * 2**attempt, max_delay)``."""

    max_attempts: int = 3
    base_delay: float = 2.0
    max_delay: float = float("inf")

    def delay_for(self, attempt: int) -> float:
        return min(self.base_delay * (2**attempt), self.max_delay)


class RateLimitGate:
    """Single shared backoff for any number of concurrent retriable calls.

    The first failure of a wave bumps the attempt counter and arms a window
    until which every caller waits. Subsequent failures inside the same window
    do not bump the counter. After max attempts, callers raise.
    """

    def __init__(self, policy: RetryPolicy, on_retry: OnRetry | None = None) -> None:
        self.policy = policy
        self.on_retry = on_retry
        self.lock = asyncio.Lock()
        self.attempt = 0
        self.unblock_at = 0.0

    async def execute[T](self, fn: Callable[[], Awaitable[T]], is_retriable: IsRetriable) -> T:
        """Run ``fn`` under the gate. Coordinates retries across siblings."""
        last_exc: Exception | None = None
        while True:
            await self.wait_if_blocked()
            try:
                result = await fn()
                async with self.lock:
                    self.attempt = 0
                return result
            except Exception as exc:
                if not is_retriable(exc):
                    raise
                last_exc = exc
                async with self.lock:
                    if time.monotonic() >= self.unblock_at:
                        self.attempt += 1
                        if self.attempt >= self.policy.max_attempts:
                            raised = self.attempt
                            self.attempt = 0
                            raise type(exc)(f"retry budget exhausted after {raised} attempts") from last_exc
                        self.unblock_at = time.monotonic() + self.policy.delay_for(self.attempt - 1)

    async def wait_if_blocked(self) -> None:
        """Block until ``unblock_at`` passes. Ticks ``on_retry`` once per second."""
        while True:
            remaining = self.unblock_at - time.monotonic()
            if remaining <= 0:
                return
            if self.on_retry:
                self.on_retry(self.attempt, remaining)
            await asyncio.sleep(min(1.0, remaining))
