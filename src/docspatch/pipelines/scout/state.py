"""Data shapes for the scout pipeline.

``ScoutBatch`` and ``ScoutResult`` travel through the checkpointer, so they are
Pydantic models. ``FileMiss`` and ``ScanPlan`` never enter graph state.
"""

from dataclasses import dataclass
from operator import add
from typing import Annotated, NamedTuple, TypedDict

from pydantic import BaseModel, ConfigDict

from docspatch.schemas import FileSummary


class FileMiss(NamedTuple):
    """A file with no fresh cached summary. Source read and compressed upfront.

    ``prior`` holds the previous summary when the file changed (used to write a
    change_note); it is None for a first-time summary.
    """

    path: str
    source: str
    compressed: str
    content_hash: str
    prior: FileSummary | None = None


@dataclass(frozen=True)
class ScanPlan:
    """Outcome of a pre-scout cache scan: uncached paths and cost."""

    uncached: tuple[str, ...]
    cached: tuple[str, ...]
    token_estimate: int
    # Carries read+compressed source for uncached entries so execute reuses it.
    misses: tuple[FileMiss, ...] = ()

    @property
    def uncached_count(self) -> int:
        """Count files that require scouting.

        Returns:
            The number of files currently missing from cache.
        """
        return len(self.uncached)

    @property
    def cached_count(self) -> int:
        """Count files that are already cached.

        Returns:
            The number of cached files.
        """
        return len(self.cached)

    @property
    def all_current(self) -> bool:
        """Check if all files have been scouted.

        Returns:
            True if no files are missing from the cache, False otherwise.
        """
        return not self.uncached


class ScoutBatch(BaseModel):
    """One LLM call's worth of files. Carries paths only; bodies live in context."""

    model_config = ConfigDict(frozen=True)

    id: int
    paths: list[str]


class ScoutResult(BaseModel):
    """Counts for one batch, or for a whole run once aggregated.

    Token counts are real provider usage, summed across the batch's calls.
    """

    model_config = ConfigDict(frozen=True)

    scouted: int
    skipped: int
    input_tokens: int = 0
    output_tokens: int = 0
    unresolved: tuple[str, ...] = ()


class ScoutState(TypedDict, total=False):
    """Summarise-graph state. Reducers accumulate worker output across waves."""

    batches: list[ScoutBatch]
    completed_batches: Annotated[list[int], add]
    results: Annotated[list[ScoutResult], add]
