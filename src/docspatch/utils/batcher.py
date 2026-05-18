"""Greedy token-based batcher.

Invariant: items are atomic. A batcher never splits, truncates, or reformats
an item. Each item enters exactly one batch as-is. If an item alone exceeds
`limit`, it lands in its own batch with `oversized=True` so callers can surface
a UX message instead of dropping it.

Splitting an item's *content* (e.g. a function body, a file) is out of scope —
that is the caller's responsibility, performed before batching.

Reusable across pipelines: scout (files), docs (functions), readme (sections).
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Batch[T]:
    """A group of atomic items whose combined size is ≤ `limit`.

    Attributes:
        items: Items included in this batch, in input order.
        total_size: Sum of `size_fn(item)` across `items`.
        oversized: True when this batch contains a single item whose size
            exceeded `limit`. Callers should send oversized batches alone
            and warn the user (e.g. raise `batch_token_limit`).
    """

    items: tuple[T, ...]
    total_size: int
    oversized: bool = False

    def __post_init__(self) -> None:
        if self.total_size < 0:
            raise ValueError("total_size must be non-negative")
        if self.oversized and len(self.items) != 1:
            raise ValueError("oversized batch must contain exactly one item")


@dataclass(frozen=True)
class BatchPlan[T]:
    """Result of `greedy_batches`. Carries derived counts to avoid recomputation."""

    batches: tuple[Batch[T], ...] = field(default_factory=tuple)

    @property
    def batch_count(self) -> int:
        return len(self.batches)

    @property
    def item_count(self) -> int:
        return sum(len(b.items) for b in self.batches)

    @property
    def oversized_count(self) -> int:
        return sum(1 for b in self.batches if b.oversized)

    @property
    def total_size(self) -> int:
        return sum(b.total_size for b in self.batches)


def greedy_batches[T](
    items: Iterable[T],
    size_fn: Callable[[T], int],
    limit: int,
) -> BatchPlan[T]:
    """Greedy-fill batches up to `limit`. Items are atomic — never split.

    Args:
        items: Iterable of atomic units. Order is preserved across batches.
        size_fn: Returns the cost (e.g. token estimate) of including `item`
            as-is. Must return ≥ 0; negative values raise `ValueError`.
        limit: Maximum total size per batch. Must be > 0.

    Returns:
        BatchPlan whose batches together contain every input item exactly
        once. Single items exceeding `limit` are emitted as `oversized=True`
        batches so callers can surface a UX message without dropping work.

    Raises:
        ValueError: If `limit <= 0` or `size_fn` returns a negative value.
    """
    if limit <= 0:
        raise ValueError("limit must be positive")

    batches: list[Batch[T]] = []
    current: list[T] = []
    current_size = 0

    def flush() -> None:
        nonlocal current, current_size
        if current:
            batches.append(Batch(tuple(current), current_size))
            current, current_size = [], 0

    for item in items:
        size = size_fn(item)
        if size < 0:
            raise ValueError(f"size_fn returned negative size ({size}) for {item!r}")
        if size > limit:
            flush()
            batches.append(Batch((item,), size, oversized=True))
            continue
        if current_size + size > limit:
            flush()
        current.append(item)
        current_size += size

    flush()
    return BatchPlan(tuple(batches))
