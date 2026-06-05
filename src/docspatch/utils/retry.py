"""Retries operations using exponential backoff policies and rate limit gates."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from docspatch.utils.errors import TransientExhausted

OnRetry = Callable[[int, float], None]
IsRetriable = Callable[[Exception], bool]


@dataclass(frozen=True)
class RetryPolicy:
    """Exponential backoff with cap. ``delay = min(base_delay * 2**attempt, max_delay)``."""

    max_attempts: int = 3
    base_delay: float = 2.0
    max_delay: float = float("inf")

    def delay_for(self, attempt: int) -> float:
        """Compute an exponential backoff delay based on the failure attempt index.

        Args:
            attempt: Index of the current failure attempt.

        Returns:
            Delay duration in seconds.
        """
        return min(self.base_delay * (2**attempt), self.max_delay)


# Shared LLM rate-limit policy. Lives here (not in the langchain-backed runnable)
# so light consumers like the retry display can read it without the SDK import.
LLM_RETRY = RetryPolicy(max_attempts=5, base_delay=60.0, max_delay=300.0)


class RateLimitGate:
    """Single shared backoff for any number of concurrent retriable calls.

    The first failure of a wave bumps the attempt counter and arms a window
    until which every caller waits. Subsequent failures inside the same window
    do not bump the counter. After max attempts, callers raise.
    """

    def __init__(self, policy: RetryPolicy, on_retry: OnRetry | None = None) -> None:
        """Initialize the rate limit gate using a retry policy and callback.

        Args:
            policy: Retry policy defining delay durations.
            on_retry: Optional callback function triggered when retrying.
        """
        self.policy = policy
        self.on_retry = on_retry
        self.lock = asyncio.Lock()
        self.attempt = 0
        self.unblock_at = 0.0

    async def execute[T](self, fn: Callable[[], Awaitable[T]], is_retriable: IsRetriable) -> T:
        """Execute an asynchronous function, retrying on matched exceptions using exponential backoff.

        Args:
            fn: Asynchronous callable to evaluate.
            is_retriable: Predicate to evaluate if an exception qualifies for retry.

        Returns:
            Value returned by the executed function.

        Raises:
            TransientExhausted: The maximum retry attempts defined by the policy are reached.
        """
        last_exc: Exception | None = None
        while True:
            await self.wait_if_blocked()
            try:
                result = await fn()
                async with self.lock:
                    # Clear the armed window too — provider recovered, no reason for
                    # subsequent siblings to keep sleeping until a stale unblock_at.
                    self.attempt = 0
                    self.unblock_at = 0.0
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
                            raise TransientExhausted.after(raised, last_exc) from last_exc
                        self.unblock_at = time.monotonic() + self.policy.delay_for(self.attempt - 1)

    async def wait_if_blocked(self) -> None:
        """Pause execution while the rate limit gate remains blocked by a retry window."""
        while True:
            remaining = self.unblock_at - time.monotonic()
            if remaining <= 0:
                return
            if self.on_retry:
                self.on_retry(self.attempt, remaining)
            await asyncio.sleep(min(1.0, remaining))
