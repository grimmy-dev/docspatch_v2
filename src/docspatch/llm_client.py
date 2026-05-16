"""LLM provider adapter. Normalises Anthropic, OpenAI, and Gemini behind one interface."""

import time
from dataclasses import dataclass
from typing import Any, TypeVar

from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from docspatch.errors import ConfigError, LLMError
from docspatch.types.llm import StructuredChain

T = TypeVar("T")

MAX_RETRIES = 3
RETRY_DELAY = 2.0  # seconds; base delay, multiplied by attempt number

TRANSIENT_MARKERS = ("rate_limit", "429", "503", "502", "timeout", "overloaded")


@dataclass
class TierInfo:
    tier: str
    model: str
    price_input_per_1m: float
    price_output_per_1m: float
    icon: str = ""


TIER_CATALOGUE: dict[str, list[TierInfo]] = {
    "anthropic": [
        TierInfo("fast", "claude-haiku-4-5-20251001", 1.00, 5.00, "⚡"),
        TierInfo("balanced", "claude-sonnet-4-6", 3.00, 15.00, "⚖️"),
        TierInfo("best", "claude-opus-4-7", 5.00, 25.00, "🏆"),
    ],
    "openai": [
        TierInfo("fast", "gpt-4o-mini", 0.15, 0.60, "⚡"),
        TierInfo("balanced", "gpt-5.4", 2.50, 15.00, "⚖️"),
        TierInfo("best", "gpt-5.5", 5.00, 30.00, "🏆"),
    ],
    "gemini": [
        TierInfo("fast", "gemini-3.1-flash-lite", 0.25, 1.50, "⚡"),
        TierInfo("balanced", "gemini-3-flash", 0.50,  3.00, "⚖️"),
        TierInfo("best", "gemini-2.5-pro", 2.00, 12.00, "🏆"),
    ],
}


def resolve_tier_model(provider: str, tier: str) -> str:
    for entry in TIER_CATALOGUE[provider]:
        if entry.tier == tier:
            return entry.model
    raise ConfigError(f"Unknown tier: {tier!r}", hint="Choose: fast, balanced, best")


def is_transient(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in TRANSIENT_MARKERS)


def build_llm(provider: str, api_key: str, tier: str) -> Any:
    model = resolve_tier_model(provider, tier)
    if provider == "anthropic":
        return ChatAnthropic(model_name=model, api_key=api_key)
    if provider == "openai":
        return ChatOpenAI(model=model, api_key=api_key)
    if provider == "gemini":
        return ChatGoogleGenerativeAI(model=model, google_api_key=api_key)
    raise ConfigError(f"Unknown provider: {provider!r}", hint="Choose: anthropic, openai, gemini")


class LLMClient:
    """Single interface over Anthropic, OpenAI, and Gemini via LangChain."""

    def __init__(self, provider: str, api_key: str, generator_tier: str = "fast") -> None:
        if provider not in TIER_CATALOGUE:
            raise ConfigError(f"Unknown provider: {provider!r}", hint="Choose: anthropic, openai, gemini")
        self.provider = provider
        self.generator_tier = generator_tier
        self.llm = build_llm(provider, api_key, generator_tier)

    @property
    def scout_model(self) -> str:
        return resolve_tier_model(self.provider, "fast")

    @property
    def generator_model(self) -> str:
        return resolve_tier_model(self.provider, self.generator_tier)

    def validate_key(self) -> bool:
        """Returns True if the API key is accepted; False on any error (no raise)."""
        try:
            self.llm.invoke("ping")
            return True
        except Exception:
            return False

    def with_structured_output(self, schema: type[T]) -> StructuredChain[T]:
        return self.llm.with_structured_output(schema)  # type: ignore[return-value]

    def invoke(self, prompt: str) -> str:
        """Invoke the generator model. Retries transient errors; raises LLMError on non-transient."""
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                result = self.llm.invoke(prompt)
                return result.content if hasattr(result, "content") else str(result)
            except Exception as exc:
                if not is_transient(exc):
                    raise LLMError(str(exc), hint="Check your API key and model availability.") from exc
                last_exc = exc
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))
        raise LLMError(str(last_exc), hint=f"Rate limit: retried {MAX_RETRIES} times.") from last_exc
