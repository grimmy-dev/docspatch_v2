"""Data shapes shared across the scout pipeline."""

from dataclasses import dataclass
from typing import NamedTuple


class FileMiss(NamedTuple):
    """A file that is not in cache (or is stale) and must be scouted.

    Source is read once and ``compressed`` is computed upfront so the batcher
    can size on real prompt cost.
    """

    path: str
    source: str
    compressed: str
    content_hash: str


@dataclass(frozen=True)
class ScanPlan:
    """Result of a pre-scout cache scan.

    Attributes:
        uncached: Paths whose cached summary is missing or stale.
        cached: Paths already up to date in cache.
        token_estimate: Sum of token estimates for ``uncached`` only.
    """

    uncached: tuple[str, ...]
    cached: tuple[str, ...]
    token_estimate: int

    @property
    def uncached_count(self) -> int:
        return len(self.uncached)

    @property
    def cached_count(self) -> int:
        return len(self.cached)

    @property
    def all_current(self) -> bool:
        return not self.uncached


@dataclass(frozen=True)
class ScoutResult:
    """Summary of a scout run."""

    scouted: int
    skipped: int
    tokens_used: int
    unresolved: tuple[str, ...] = ()
