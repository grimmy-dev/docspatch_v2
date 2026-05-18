"""Scout pipeline — cache-aware token-batched LLM summarisation.

Public surface:
- :func:`scout_files` — run the pipeline.
- :func:`plan_uncached` — pre-scout cost/coverage estimate (used by ``dp init``).
- :class:`ScoutResult`, :class:`ScanPlan`, :class:`FileMiss` — typed shapes.
"""

from docspatch.pipelines.scout.planner import partition_paths, plan_uncached
from docspatch.pipelines.scout.prompts import build_batch_prompt
from docspatch.pipelines.scout.runner import DEFAULT_BATCH_TOKEN_LIMIT, scout_files
from docspatch.pipelines.scout.types import FileMiss, ScanPlan, ScoutResult

__all__ = [
    "DEFAULT_BATCH_TOKEN_LIMIT",
    "FileMiss",
    "ScanPlan",
    "ScoutResult",
    "build_batch_prompt",
    "partition_paths",
    "plan_uncached",
    "scout_files",
]
