"""Token cost estimation. Separates input and output dollar math.

Earlier code multiplied ``(input_price + output_price)`` by input-token count,
treating output cost as if it scaled with input tokens — that overstates cost
2-5× depending on provider. This module projects output tokens as a fraction
of input and prices each side independently.
"""

from dataclasses import dataclass

from docspatch.llm.catalogue import tier_info
from docspatch.utils.errors import ConfigError

# Scout summaries measure ~15% of compressed input across Python files.
# Callers override per-pipeline (docs/readme generate more).
DEFAULT_OUTPUT_RATIO = 0.15


@dataclass(frozen=True)
class CostEstimate:
    input_tokens: int
    output_tokens: int
    input_cost: float
    output_cost: float

    @property
    def total(self) -> float:
        return self.input_cost + self.output_cost


def estimate_cost(
    provider: str,
    tier: str,
    input_tokens: int,
    output_ratio: float = DEFAULT_OUTPUT_RATIO,
) -> CostEstimate:
    """Estimate dollar cost for a pipeline run.

    Args:
        provider: One of ``anthropic``, ``openai``, ``gemini``.
        tier: One of ``fast``, ``balanced``, ``best``.
        input_tokens: Total input tokens for the run.
        output_ratio: Projected output tokens as a fraction of input. Must be ≥ 0.

    Raises:
        ConfigError: On unknown provider/tier or negative inputs.
    """
    if input_tokens < 0:
        raise ConfigError.must_be_non_negative("input_tokens", input_tokens)
    if output_ratio < 0:
        raise ConfigError.must_be_non_negative("output_ratio", output_ratio)

    info = tier_info(provider, tier)
    output_tokens = int(input_tokens * output_ratio)
    input_cost = (input_tokens / 1_000_000) * info.price_input_per_1m
    output_cost = (output_tokens / 1_000_000) * info.price_output_per_1m
    return CostEstimate(input_tokens, output_tokens, input_cost, output_cost)


def actual_cost(provider: str, tier: str, input_tokens: int, output_tokens: int) -> CostEstimate:
    """Dollar cost from measured input *and* output tokens — no projection.

    Used by the end-of-run summary, where both token counts are known for real.
    """
    if input_tokens < 0 or output_tokens < 0:
        raise ConfigError.must_be_non_negative("tokens", min(input_tokens, output_tokens))
    info = tier_info(provider, tier)
    input_cost = (input_tokens / 1_000_000) * info.price_input_per_1m
    output_cost = (output_tokens / 1_000_000) * info.price_output_per_1m
    return CostEstimate(input_tokens, output_tokens, input_cost, output_cost)
