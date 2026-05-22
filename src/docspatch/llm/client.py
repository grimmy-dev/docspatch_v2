"""Single client over Anthropic / OpenAI / Gemini via LangChain, with retry-aware chains."""

from typing import cast

from langchain_core.runnables import Runnable

from docspatch.llm.catalogue import resolve_tier_model
from docspatch.llm.factory import build_llm, build_validator_llm
from docspatch.llm.runnable import LLM_RETRY, TypedRunnable, is_transient, wrap_llm_error
from docspatch.schemas import Provider, Tier, as_provider, as_tier
from docspatch.utils import key_cache
from docspatch.utils.retry import OnRetry, RateLimitGate
from docspatch.utils.secrets import register_secret

RetryCallback = OnRetry

__all__ = ["LLM_RETRY", "LLMClient", "RetryCallback", "is_transient", "wrap_llm_error"]


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
        register_secret(api_key)  # mask this key in any later error/log text
        self.llm = build_llm(self.provider, api_key, self.generator_tier)
        self.retry_cb = retry_cb
        self.gate = RateLimitGate(LLM_RETRY, on_retry=retry_cb)

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

    def with_structured_output[T](self, schema: type[T]) -> TypedRunnable[T]:
        base_chain = cast(
            Runnable[str, T],
            self.llm.with_structured_output(schema),
        )
        return TypedRunnable[T](base_chain, self.gate)
