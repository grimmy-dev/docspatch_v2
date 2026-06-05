"""Declares token estimation and actual pricing models to calculate run costs."""

from dataclasses import dataclass

from docspatch.llm.catalogue import tier_info
from docspatch.utils.errors import ConfigError

# Output-token fraction of input, per pipeline — measured, independently tunable.
# Docs: full function source in, moderate docstrings out.
DOCS_OUTPUT_RATIO = 0.5
DEFAULT_OUTPUT_RATIO = 0.6


@dataclass(frozen=True)
class CostEstimate:
    input_tokens: int
    output_tokens: int
    input_cost: float
    output_cost: float

    @property
    def total(self) -> float:
        """Calculate the total combined cost of input and output tokens.

        Returns:
            Total cost.
        """
        return self.input_cost + self.output_cost


def estimate_cost(
    provider: str,
    tier: str,
    input_tokens: int,
    output_ratio: float = DEFAULT_OUTPUT_RATIO,
) -> CostEstimate:
    """Predict the dollar cost of a run using an expected output-to-input token ratio.

    Args:
        provider: LLM provider name.
        tier: Performance tier.
        input_tokens: Total input tokens.
        output_ratio: Estimated output token fraction.

    Returns:
        Cost estimate object.

    Raises:
        ConfigError: Inputs are invalid or configurations are unknown.
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
    """Compute the exact cost of an executed model call using physical token usage counts.

    Args:
        provider: Target LLM provider.
        tier: Model quality tier.
        input_tokens: Measured input tokens.
        output_tokens: Measured output tokens.

    Returns:
        Cost estimate object.
    """
    if input_tokens < 0 or output_tokens < 0:
        raise ConfigError.must_be_non_negative("tokens", min(input_tokens, output_tokens))
    info = tier_info(provider, tier)
    input_cost = (input_tokens / 1_000_000) * info.price_input_per_1m
    output_cost = (output_tokens / 1_000_000) * info.price_output_per_1m
    return CostEstimate(input_tokens, output_tokens, input_cost, output_cost)
