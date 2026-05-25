"""Append-only token ledger — one jsonl line per generator call.

The ledger records the *real* tokens each LLM call billed, so the final summary
reports actual usage rather than the planner's estimate. It is a plain file
keyed by run id, so it survives a resume (appends accumulate) and is deleted
once the run completes.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from docspatch.llm import TokenUsage


class TokenLedger:
    """Append-only record at ``.docspatch/checkpoints/ledger-<run_id>.jsonl``."""

    def __init__(self, checkpoint_dir: Path, run_id: str) -> None:
        """Initialize the token ledger with a specific checkpoint directory and run identifier.

        Args:
            checkpoint_dir: The directory where checkpoint files are stored.
            run_id: A unique identifier for the current execution run.
        """
        self.path = checkpoint_dir / f"ledger-{run_id}.jsonl"
        # Seed accumulator from any existing file once, so totals() is O(1) thereafter.
        self._total = _read_totals(self.path)

    def append(self, batch_id: int, usage: TokenUsage) -> None:
        """Record one generator call's real token usage."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "batch_id": batch_id,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "ts": time.time(),
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        # File authoritative; rebind only after write lands.
        self._total += usage

    def totals(self) -> TokenUsage:
        """Sum every recorded call's tokens (zero when nothing recorded)."""
        return self._total

    def delete(self) -> None:
        """Remove the ledger file — called once a run finishes successfully."""
        self.path.unlink(missing_ok=True)
        self._total = TokenUsage()


def _read_totals(path: Path) -> TokenUsage:
    """Sum a ledger file from disk. Used once at construction; tolerates absence.

    Skips malformed lines silently — a partial line from a hard crash mid-write
    must not block the resume.
    """
    total = TokenUsage()
    if not path.exists():
        return total
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            total += TokenUsage(int(record["input_tokens"]), int(record["output_tokens"]))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
    return total
