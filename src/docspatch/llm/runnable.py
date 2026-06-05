"""Supplies the main execution harness for retrying model operations and collecting usage data."""

from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.exceptions import OutputParserException
from langchain_core.runnables import Runnable
from pydantic import ValidationError

from docspatch.llm.usage import TokenUsage
from docspatch.utils.errors import LLMError, ParseFailed, TransientExhausted
from docspatch.utils.retry import LLM_RETRY, RateLimitGate

TRANSIENT_MARKERS = ("rate_limit", "429", "503", "502", "timeout", "overloaded")

PARSE_RETRY_SUFFIX = "\n\nReturn valid JSON matching the schema exactly. Previous response failed validation."
_PARSE_ERRORS = (OutputParserException, ValidationError)
"""Schema-validation failures: json mode raises the first, tool-calling the second."""


def _collected_usage(handler: UsageMetadataCallbackHandler) -> TokenUsage:
    """Aggregate total tokens tracked across all models queried in a callback handler.

    Args:
        handler: Langchain callback recording token usage metadata.

    Returns:
        Total token usage.
    """
    total = TokenUsage()
    for meta in handler.usage_metadata.values():
        total += TokenUsage(int(meta.get("input_tokens", 0)), int(meta.get("output_tokens", 0)))
    return total


def is_transient(exc: Exception) -> bool:
    """Determine if an exception represents a retryable rate limit or timeout error.

    Args:
        exc: The caught exception.

    Returns:
        True if error is transient.
    """
    msg = str(exc).lower()
    return any(marker in msg for marker in TRANSIENT_MARKERS)


def wrap_llm_error(exc: Exception) -> LLMError:
    """Convert provider exceptions into TransientExhausted or generic LLMError wrappers.

    Args:
        exc: The raw exception caught from the LLM provider.

    Returns:
        An instance of TransientExhausted or LLMError.
    """
    if is_transient(exc):
        return TransientExhausted.after(LLM_RETRY.max_attempts, exc)
    return LLMError.api_failure(exc)


class TypedRunnable[T]:
    """Wraps a LangChain structured chain with the gate + parse-retry policy."""

    def __init__(self, chain: Runnable[str, T], gate: RateLimitGate) -> None:
        """Store the LangChain runnable chain and rate limiter on the wrapper instance.

        Args:
            chain: The base runnable chain.
            gate: The rate limiting manager.
        """
        self.chain = chain
        self.gate = gate

    async def ainvoke(self, prompt: str) -> tuple[T, TokenUsage]:
        """Invoke the chain asynchronously and trigger a single schema-validation retry on failure.

        Args:
            prompt: The input text for the LLM chain.

        Returns:
            The parsed value and the accumulated token usage.

        Raises:
            ParseFailed: A second schema-validation error occurs after retry.
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
        """Invoke the chain through a rate-limiting gate while recording token usage metadata.

        Args:
            prompt: The input text for the LLM chain.
            handler: The usage tracking callback handler.

        Returns:
            The result of the invocation.

        Raises:
            LLMError: The provider reports an API failure.
        """
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
