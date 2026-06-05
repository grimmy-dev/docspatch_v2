"""Contains the TokenUsage dataclass to track and combine input and output token counts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TokenUsage:
    """Real input/output token counts reported by a provider for one or more calls."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        """Calculate the sum of input and output tokens.

        Returns:
            Sum of tokens.
        """
        return self.input_tokens + self.output_tokens

    def __add__(self, other: TokenUsage) -> TokenUsage:
        """Add the token counts of another usage instance to create a new combined total.

        Args:
            other: Another usage instance.

        Returns:
            Combined usage.
        """
        return TokenUsage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
        )
