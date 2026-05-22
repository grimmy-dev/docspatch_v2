"""Shared run-summary rows: real-token cost and cache-hit ratio."""

from docspatch.llm import TokenUsage
from docspatch.ui.summary import cache_hit_row, cost_rows


def test_cost_rows_report_real_input_and_output_tokens() -> None:
    rows = dict(cost_rows(TokenUsage(1000, 500), "anthropic", "fast"))
    assert rows["Tokens in / out"] == "1,000 / 500"
    assert rows["Cost"].startswith("$")


def test_cost_rows_label_marks_sunk_cost_on_abort() -> None:
    rows = dict(cost_rows(TokenUsage(10, 5), "anthropic", "fast", sunk=True))
    assert "Tokens (sunk cost)" in rows


def test_cache_hit_row_shows_ratio_and_percent() -> None:
    assert cache_hit_row(3, 12) == ("Cache hits", "3/12 (25%)")


def test_cache_hit_row_handles_zero_total() -> None:
    assert cache_hit_row(0, 0) == ("Cache hits", "0/0")
