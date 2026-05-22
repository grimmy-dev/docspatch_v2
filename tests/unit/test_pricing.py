"""Pricing math — exact dollar values, not approximate."""

import pytest

from docspatch.llm.pricing import estimate_cost
from docspatch.utils.errors import ConfigError


def test_estimate_separates_input_and_output_cost():
    # anthropic/fast: $1.00 input, $5.00 output per 1M
    est = estimate_cost("anthropic", "fast", input_tokens=1_000_000, output_ratio=0.2)

    assert est.input_tokens == 1_000_000
    assert est.output_tokens == 200_000
    assert est.input_cost == pytest.approx(1.00)
    assert est.output_cost == pytest.approx(1.00)
    assert est.total == pytest.approx(2.00)


def test_estimate_zero_input_tokens():
    est = estimate_cost("openai", "balanced", input_tokens=0)
    assert est.total == 0.0
    assert est.input_tokens == 0
    assert est.output_tokens == 0


def test_estimate_zero_output_ratio_excludes_output_cost():
    est = estimate_cost("openai", "fast", input_tokens=1_000_000, output_ratio=0.0)
    # input only: $0.15 per 1M
    assert est.output_cost == 0.0
    assert est.total == pytest.approx(0.15)


def test_estimate_unknown_provider_raises():
    with pytest.raises(ConfigError):
        estimate_cost("llama", "fast", 100)


def test_estimate_unknown_tier_raises():
    with pytest.raises(ConfigError):
        estimate_cost("anthropic", "ultra", 100)


def test_estimate_negative_inputs_raise():
    with pytest.raises(ConfigError):
        estimate_cost("anthropic", "fast", -1)
    with pytest.raises(ConfigError):
        estimate_cost("anthropic", "fast", 100, output_ratio=-0.1)


def test_old_buggy_formula_is_not_returned():
    """Regression: cost must not be `tokens × (input_price + output_price)`."""
    est = estimate_cost("anthropic", "fast", input_tokens=1_000_000, output_ratio=0.15)
    # Old formula: 1M * (1.00 + 5.00) / 1M = 6.00 — must not appear.
    assert est.total != pytest.approx(6.00)
    # Correct: 1.00 (input) + 150_000/1M × 5.00 = 1.00 + 0.75 = 1.75
    assert est.total == pytest.approx(1.75)
