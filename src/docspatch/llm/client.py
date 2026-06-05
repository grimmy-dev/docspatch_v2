"""Implement the core LLM client for interacting with various generation models."""

from typing import cast

from langchain_core.runnables import Runnable

from docspatch.llm.catalogue import resolve_tier_model
from docspatch.llm.factory import build_llm, build_validator_llm
from docspatch.llm.runnable import LLM_RETRY, TypedRunnable, is_transient, wrap_llm_error
from docspatch.schemas import Provider, Tier, as_provider, as_tier
from docspatch.utils import key_cache
from docspatch.utils.errors import ConfigError
from docspatch.utils.retry import OnRetry, RateLimitGate
from docspatch.utils.secrets import register_secret

RetryCallback = OnRetry

__all__ = ["LLM_RETRY", "LLMClient", "RetryCallback", "is_transient", "validate_api_key", "wrap_llm_error"]


def validate_api_key(provider: str, api_key: str) -> bool:
    """Verify if a provider accepts the provided API key without instantiating the full client.

    Args:
        provider: Target provider.
        api_key: Key to validate.

    Returns:
        True if valid.
    """
    return LLMClient(provider=provider, api_key=api_key).validate_key()


class LLMClient:
    """Provider-normalised LLM interface."""

    def __init__(
        self,
        provider: str,
        api_key: str,
        generator_tier: str = "fast",
        retry_cb: RetryCallback | None = None,
    ) -> None:
        """Initialize the LLM client with a provider and settings.

        Args:
            provider: Name of the LLM provider.
            api_key: Authentication credentials.
            generator_tier: Performance tier for text generation.
            retry_cb: Callback for tracking retries.
        """
        self.provider: Provider = as_provider(provider)
        self.generator_tier: Tier = as_tier(generator_tier)
        # Fail fast at the edge — empty key would surface as a cryptic provider error later.
        if not api_key or not api_key.strip():
            raise ConfigError.missing_api_key(self.provider)
        self._api_key = api_key
        register_secret(api_key)  # mask this key in any later error/log text
        self.llm = build_llm(self.provider, api_key, self.generator_tier)
        self.retry_cb = retry_cb
        self.gate = RateLimitGate(LLM_RETRY, on_retry=retry_cb)

    @property
    def analysis_model(self) -> str:
        """Return the identifier for the fast model used for analysis tasks.

        Returns:
            Fast tier model identifier.
        """
        return resolve_tier_model(self.provider, "fast")

    @property
    def generator_model(self) -> str:
        """Return the identifier for the model used for primary generation tasks.

        Returns:
            Generator model identifier.
        """
        return resolve_tier_model(self.provider, self.generator_tier)

    def validate_key(self) -> bool:
        """Verify the provided API key against the model provider.

        Returns:
            True if valid.
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
        """Configure the client to produce outputs adhering to a specific Pydantic schema.

        Args:
            schema: Pydantic model for validation.

        Returns:
            Runnable instance.
        """
        base_chain = cast(
            Runnable[str, T],
            self.llm.with_structured_output(schema),
        )
        return TypedRunnable[T](base_chain, self.gate)
