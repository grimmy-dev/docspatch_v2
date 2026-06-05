"""Partitions work items into size-bounded batches using greedy allocation."""

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
        """Validate internal size limits and item count invariants for standard and oversized batches.

        Raises:
            ValueError: The total size is negative, or an oversized batch contains more or less than one item.
        """
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
        """Return the total number of processed batches in the plan.

        Returns:
            Number of generated batches.
        """
        return len(self.batches)

    @property
    def item_count(self) -> int:
        """Calculate the aggregate number of items across all batches.

        Returns:
            Sum of items across all batches.
        """
        return sum(len(b.items) for b in self.batches)

    @property
    def oversized_count(self) -> int:
        """Count the number of batches categorized as oversized.

        Returns:
            Number of oversized batches.
        """
        return sum(1 for b in self.batches if b.oversized)

    @property
    def total_size(self) -> int:
        """Calculate the cumulative size of all items across all batches.

        Returns:
            Sum of all batch sizes.
        """
        return sum(b.total_size for b in self.batches)


def greedy_batches[T](
    items: Iterable[T],
    size_fn: Callable[[T], int],
    limit: int,
) -> BatchPlan[T]:
    """Partition a collection of items into batches constrained by a maximum size limit.

    Args:
        items: Sequence of elements to pack.
        size_fn: Function to compute the numeric footprint of an individual item.
        limit: Maximum cumulative size allowed in a single batch.

    Returns:
        A BatchPlan organizing the items into structured batches.

    Raises:
        ValueError: The limit is non-positive or size_fn returns a negative item size.
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
