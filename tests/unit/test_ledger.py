"""TokenLedger: append-only real-token record, survives resumes, deleted on success."""

from pathlib import Path

from docspatch.checkpoints.ledger import TokenLedger
from docspatch.llm import TokenUsage


def test_append_and_totals(tmp_path: Path) -> None:
    ledger = TokenLedger(tmp_path, "r1")
    ledger.append(0, TokenUsage(10, 4))
    ledger.append(1, TokenUsage(5, 2))
    assert ledger.totals() == TokenUsage(15, 6)


def test_totals_empty_when_nothing_recorded(tmp_path: Path) -> None:
    assert TokenLedger(tmp_path, "r1").totals() == TokenUsage(0, 0)


def test_ledger_preserved_across_instances(tmp_path: Path) -> None:
    TokenLedger(tmp_path, "r1").append(0, TokenUsage(3, 1))
    # A resumed run opens a fresh TokenLedger for the same run id.
    assert TokenLedger(tmp_path, "r1").totals() == TokenUsage(3, 1)


def test_delete_clears_the_ledger(tmp_path: Path) -> None:
    ledger = TokenLedger(tmp_path, "r1")
    ledger.append(0, TokenUsage(1, 1))
    ledger.delete()
    assert ledger.totals() == TokenUsage(0, 0)
