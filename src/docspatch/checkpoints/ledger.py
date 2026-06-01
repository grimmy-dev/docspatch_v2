"""Token usage accounting for LLM operations."""

from __future__ import annotations

import json
import time
from pathlib import Path

from docspatch.llm import TokenUsage


class TokenLedger:
    """Append-only record at ``.docspatch/checkpoints/ledger-<run_id>.jsonl``."""

    def __init__(self, checkpoint_dir: Path, run_id: str) -> None:
        """Initialize a ledger tracking token consumption for a run.

        Args:
            checkpoint_dir: Directory for storing ledger logs.
            run_id: Identifier for the current run.
        """
        self.path = checkpoint_dir / f"ledger-{run_id}.jsonl"
        # Seed accumulator from any existing file once, so totals() is O(1) thereafter.
        self._total = _read_totals(self.path)

    def append(self, batch_id: int, usage: TokenUsage) -> None:
        """Log token usage for a completed operation.

        Args:
            batch_id: Identifier of the batch.
            usage: Usage statistics to record.
        """
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
        """Return the cumulative token usage for this run.

        Returns:
            Token usage object.
        """
        return self._total

    def delete(self) -> None:
        """Discard the ledger file after task completion."""
        self.path.unlink(missing_ok=True)
        self._total = TokenUsage()


def _read_totals(path: Path) -> TokenUsage:
    """Calculate total tokens by parsing an existing ledger file.

    Args:
        path: Path to the ledger log.

    Returns:
        Accumulated usage stats.
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
        except json.JSONDecodeError, KeyError, TypeError, ValueError:
            continue
    return total
