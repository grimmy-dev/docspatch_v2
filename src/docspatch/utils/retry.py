"""Async retry with exponential backoff. Predicate-driven, domain-agnostic.

Reusable across any awaitable I/O that exhibits transient failure (LLM calls,
remote git, registries). Callers supply the retriable-predicate and policy so
this module stays decoupled from any one domain.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

OnRetry = Callable[[int, float], None]
IsRetriable = Callable[[Exception], bool]


@dataclass(frozen=True)
class RetryPolicy:
    """Exponential backoff policy. ``delay = base_delay * 2**attempt``."""

    max_attempts: int = 3
    base_delay: float = 2.0

    def delay_for(self, attempt: int) -> float:
        delay: float = self.base_delay * (2**attempt)
        return delay


async def retry_async[T](
    fn: Callable[[], Awaitable[T]],
    *,
    is_retriable: IsRetriable,
    policy: RetryPolicy,
    on_retry: OnRetry | None = None,
) -> T:
    """Await ``fn`` until success, exhaustion, or non-retriable exception.

    Non-retriable exceptions propagate verbatim. On exhaustion the last
    retriable exception is re-raised — callers wrap into a domain-specific
    error if they need framing.
    """
    last_exc: Exception | None = None
    for attempt in range(policy.max_attempts):
        try:
            return await fn()
        except Exception as exc:
            if not is_retriable(exc):
                raise
            last_exc = exc
            if attempt < policy.max_attempts - 1:
                delay = policy.delay_for(attempt)
                if on_retry:
                    on_retry(attempt + 1, delay)
                await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc
