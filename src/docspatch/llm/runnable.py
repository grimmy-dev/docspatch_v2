"""Typed, retry-aware async runnable returned by ``LLMClient.with_structured_output``.

Two retry mechanisms, kept distinct:
- Transient errors (rate limit / 5xx / timeout) → the shared ``RateLimitGate``.
- Schema-validation failure → one corrective re-prompt here, then ``ParseFailed``.

Real token usage is captured with a per-call ``UsageMetadataCallbackHandler``;
a fresh handler per call keeps usage isolated under concurrent batches.
"""

from dataclasses import dataclass

from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.exceptions import OutputParserException
from langchain_core.runnables import Runnable
from pydantic import ValidationError

from docspatch.utils.errors import LLMError, ParseFailed, TransientExhausted
from docspatch.utils.retry import RateLimitGate, RetryPolicy

LLM_RETRY = RetryPolicy(max_attempts=5, base_delay=60.0, max_delay=300.0)
TRANSIENT_MARKERS = ("rate_limit", "429", "503", "502", "timeout", "overloaded")

PARSE_RETRY_SUFFIX = (
    "\n\nReturn valid JSON matching the schema exactly. Previous response failed validation."
)
_PARSE_ERRORS = (OutputParserException, ValidationError)
"""Schema-validation failures: json mode raises the first, tool-calling the second."""


@dataclass(frozen=True)
class TokenUsage:
    """Real input/output token counts reported by a provider for one or more calls."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        """Calculate the aggregate number of tokens.

        Returns:
            The total count of input and output tokens.
        """
        return self.input_tokens + self.output_tokens

    def __add__(self, other: TokenUsage) -> TokenUsage:
        """Sum two token usage instances.

        Args:
            other: Another instance of token usage to add.

        Returns:
            A new TokenUsage instance representing the combined count.
        """
        return TokenUsage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
        )


def _collected_usage(handler: UsageMetadataCallbackHandler) -> TokenUsage:
    """Sum the per-model usage a callback handler collected during one call."""
    total = TokenUsage()
    for meta in handler.usage_metadata.values():
        total += TokenUsage(int(meta.get("input_tokens", 0)), int(meta.get("output_tokens", 0)))
    return total


def is_transient(exc: Exception) -> bool:
    """True if ``exc`` looks like a retryable provider/rate error."""
    msg = str(exc).lower()
    return any(marker in msg for marker in TRANSIENT_MARKERS)


def wrap_llm_error(exc: Exception) -> LLMError:
    """Map a raw provider error to ``TransientExhausted`` or ``LLMError``."""
    if is_transient(exc):
        return TransientExhausted.after(LLM_RETRY.max_attempts, exc)
    return LLMError.api_failure(exc)


class TypedRunnable[T]:
    """Wraps a LangChain structured chain with the gate + parse-retry policy."""

    def __init__(self, chain: Runnable[str, T], gate: RateLimitGate) -> None:
        """Initialize the runnable with a chain and a rate limit gate.

        Args:
            chain: The base runnable chain.
            gate: The rate limiting manager.
        """
        self.chain = chain
        self.gate = gate

    async def ainvoke(self, prompt: str) -> tuple[T, TokenUsage]:
        """Invoke the chain, retrying a schema-validation failure exactly once.

        Returns the parsed value and the real token usage of every call made
        (a retry is billed too). A second parse failure raises ``ParseFailed``.
        """
        # One handler shared across both attempts so a parse-retry still bills the
        # discarded first call. Provider tokens are committed regardless of whether
        # the response validated.
        handler = UsageMetadataCallbackHandler()
        try:
            value = await self._call(prompt, handler)
        except _PARSE_ERRORS:
            try:
                value = await self._call(prompt + PARSE_RETRY_SUFFIX, handler)
            except _PARSE_ERRORS as exc:
                raise ParseFailed.after_retry(exc) from exc
        return value, _collected_usage(handler)

    async def _call(self, prompt: str, handler: UsageMetadataCallbackHandler) -> T:
        """One gated call recording usage into ``handler``. Parse errors propagate raw."""
        try:
            return await self.gate.execute(
                lambda: self.chain.ainvoke(prompt, config={"callbacks": [handler]}),
                is_transient,
            )
        except _PARSE_ERRORS:
            raise
        except LLMError:
            # Gate raises TransientExhausted directly; pass any domain LLM error through
            # untouched so wrap_llm_error's text-scan classification cannot re-tag it.
            raise
        except Exception as exc:
            raise wrap_llm_error(exc) from exc
