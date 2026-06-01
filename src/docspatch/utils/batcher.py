"""Provide utilities for batching items based on size limits."""

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
        """Validate the batch data post-initialization.

        Raises:
            ValueError: total_size is negative or oversized status is improperly assigned.
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
        """Calculate the total number of batches in the plan.

        Returns:
            Integer count.
        """
        return len(self.batches)

    @property
    def item_count(self) -> int:
        """Calculate the total number of items distributed across batches.

        Returns:
            Integer count.
        """
        return sum(len(b.items) for b in self.batches)

    @property
    def oversized_count(self) -> int:
        """Calculate the number of batches marked as oversized.

        Returns:
            Integer count.
        """
        return sum(1 for b in self.batches if b.oversized)

    @property
    def total_size(self) -> int:
        """Calculate the total size of all items across all batches.

        Returns:
            Integer count.
        """
        return sum(b.total_size for b in self.batches)


def greedy_batches[T](
    items: Iterable[T],
    size_fn: Callable[[T], int],
    limit: int,
) -> BatchPlan[T]:
    """Partition items into batches limited by a total cost.

    Args:
        items: Collection of atomic items to process.
        size_fn: Function calculating the cost for an individual item.
        limit: Maximum allowed cost per batch.

    Returns:
        A plan containing all items organized into appropriately sized batches.

    Raises:
        ValueError: The limit is non-positive or the size function returns a negative value.
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
