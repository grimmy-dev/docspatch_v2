"""Single client over Anthropic / OpenAI / Gemini via LangChain, with retry-aware chains."""

from typing import cast

from langchain_core.runnables import Runnable

from docspatch.llm.catalogue import resolve_tier_model
from docspatch.llm.factory import build_llm, build_validator_llm
from docspatch.types.llm import Provider, Tier, as_provider, as_tier
from docspatch.utils import key_cache
from docspatch.utils.errors import LLMError, TransientExhausted
from docspatch.utils.retry import OnRetry, RetryPolicy, retry_async

LLM_RETRY = RetryPolicy(max_attempts=3, base_delay=2.0)
TRANSIENT_MARKERS = ("rate_limit", "429", "503", "502", "timeout", "overloaded")

RetryCallback = OnRetry


def is_transient(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in TRANSIENT_MARKERS)


def wrap_llm_error(exc: Exception) -> LLMError:
    if is_transient(exc):
        return TransientExhausted.after(LLM_RETRY.max_attempts, exc)
    return LLMError.api_failure(exc)


class RetryingChain[T]:
    """Wraps a LangChain structured chain so ``ainvoke`` retries transient errors."""

    def __init__(self, chain: Runnable[str, T], retry_cb: RetryCallback | None = None) -> None:
        self._chain = chain
        self._retry_cb = retry_cb

    async def ainvoke(self, prompt: str) -> T:
        try:
            return await retry_async(
                lambda: self._chain.ainvoke(prompt),
                is_retriable=is_transient,
                policy=LLM_RETRY,
                on_retry=self._retry_cb,
            )
        except Exception as exc:
            raise wrap_llm_error(exc) from exc


class LLMClient:
    """Provider-normalised LLM interface."""

    def __init__(
        self,
        provider: str,
        api_key: str,
        generator_tier: str = "fast",
        retry_cb: RetryCallback | None = None,
    ) -> None:
        self.provider: Provider = as_provider(provider)
        self.generator_tier: Tier = as_tier(generator_tier)
        self._api_key = api_key
        self.llm = build_llm(self.provider, api_key, self.generator_tier)
        self.retry_cb = retry_cb

    @property
    def scout_model(self) -> str:
        return resolve_tier_model(self.provider, "fast")

    @property
    def generator_model(self) -> str:
        return resolve_tier_model(self.provider, self.generator_tier)

    def validate_key(self) -> bool:
        """True if the API key is accepted; False on any error (no raise).

        Consults the cross-process key cache first: a key validated within
        :data:`docspatch.utils.key_cache.CACHE_TTL_SECONDS` skips the network
        round-trip. Hash mismatch (key changed) bypasses the cache.
        """
        if key_cache.is_validated(self.provider, self._api_key):
            return True
        try:
            validator = build_validator_llm(self.provider, self._api_key)
            validator.invoke(".")
        except Exception:
            return False
        key_cache.mark_validated(self.provider, self._api_key)
        return True

    def with_structured_output[T](self, schema: type[T]) -> RetryingChain[T]:
        base_chain = cast(
            Runnable[str, T],
            self.llm.with_structured_output(schema),
        )
        return RetryingChain[T](base_chain, retry_cb=self.retry_cb)
