"""Contains data models and merge helpers for tracking document generation and review states."""

from operator import add
from pathlib import Path
from typing import Annotated, TypedDict

from pydantic import BaseModel, ConfigDict

from docspatch.pipelines.docs.flags import RunFlags

GenKey = tuple[str, str]
"""A ``(rel, qualname)`` pair — the identity of one documentable function."""

RERUN_ROUND_CAP = 5
"""Max rerun rounds before the review UI collapses to terminal choices."""


class TargetRef(BaseModel):
    """Pointer to one undocumented function. No source carried."""

    model_config = ConfigDict(frozen=True)

    rel: str
    qualname: str


class BatchRef(BaseModel):
    """One LLM call's worth of targets."""

    model_config = ConfigDict(frozen=True)

    id: int
    targets: list[TargetRef]


class CostBreakdown(BaseModel):
    """Renderable cost estimate for the estimator panel."""

    model_config = ConfigDict(frozen=True)

    model: str
    tier: str
    files: int
    functions: int
    input_tokens: int
    output_tokens: int
    cost: float
    per_file: list[tuple[str, int]]


class GeneratedDoc(BaseModel):
    """One generated docstring keyed by ``(rel, qualname)``.

    ``parse_failed`` marks an entry whose batch failed schema validation; its
    ``docstring`` is empty and ``raw_output`` holds the model text for review.
    """

    model_config = ConfigDict(frozen=True)

    rel: str
    qualname: str
    docstring: str
    parse_failed: bool = False
    raw_output: str | None = None

    @property
    def key(self) -> GenKey:
        """Compute the unique composite key representing the file path and qualified name.

        Returns:
            A composite key pair of file path and qualified name.
        """
        return (self.rel, self.qualname)


def merge_feedback(a: dict[str, list[str]], b: dict[str, list[str]]) -> dict[str, list[str]]:
    """Combine two review feedback dictionaries by merging lists of comments under matching keys.

    Args:
        a: The base feedback dictionary mapping keys to lists of remarks.
        b: The secondary feedback dictionary to merge into the base.

    Returns:
        A new unified feedback dictionary containing combined critique lists.
    """
    out = {k: list(v) for k, v in a.items()}
    for k, v in b.items():
        out.setdefault(k, []).extend(v)
    return out


def merge_generated(a: list[GeneratedDoc], b: list[GeneratedDoc]) -> list[GeneratedDoc]:
    """Merge lists of generated document models, resolving key duplicates in favor of the newer ones.

    Args:
        a: The baseline sequence of generated documentation results.
        b: The incoming sequence of generated documentation results to overlay.

    Returns:
        The unified list of unique generated documents.
    """
    by_key: dict[GenKey, GeneratedDoc] = {}
    for entry in (*a, *b):
        by_key[entry.key] = entry
    return list(by_key.values())


class PlanState(TypedDict, total=False):
    """Plan graph state: paths in, batches + estimate + confirmed out."""

    paths: list[Path]
    repo_root: Path
    tone: str
    flags: RunFlags
    targets: list[TargetRef]
    cache_hits: int
    batches: list[BatchRef]
    estimate: CostBreakdown
    confirmed: bool


class GenerateState(TypedDict, total=False):
    """Generate graph state. Reducers accumulate worker outputs across invocations."""

    batches: list[BatchRef]
    completed_batches: Annotated[list[int], add]
    generated: Annotated[list[GeneratedDoc], merge_generated]
    feedback: Annotated[dict[str, list[str]], merge_feedback]


class RegenerateInput(TypedDict):
    """Send payload for the regenerate node: one batch plus its rerun feedback."""

    batch: BatchRef
    feedback: dict[str, list[str]]


class ReviewState(TypedDict, total=False):
    """Finalize graph state: review → rerun loop → commit.

    ``entries`` carries every docstring; the rerun loop drives ``regenerate``
    via conditional edges off ``review``; ``commit`` writes the accepted set.
    """

    entries: Annotated[list[GeneratedDoc], merge_generated]
    feedback: Annotated[dict[str, list[str]], merge_feedback]
    accepted: list[str]
    rejected: list[str]
    review_round: int
    pending_rerun: list[BatchRef]
    aborted: bool
    committed_files: list[str]
    skipped_files: list[str]
    commit_error: str


class DocsResult(BaseModel):
    """Final run counts returned by ``run_docs``."""

    model_config = ConfigDict(frozen=True)

    functions_documented: int
    files_documented: int
    batches: int
    modules_documented: int = 0
    confirmed: bool = True
    aborted: bool = False
    skipped_files: int = 0
    error: str | None = None


class FinalizeResult(BaseModel):
    """Outcome of the review → commit graph."""

    model_config = ConfigDict(frozen=True)

    committed: list[str]
    skipped: list[str]
    fn_count: int
    module_count: int = 0
    error: str | None = None
    aborted: bool = False
