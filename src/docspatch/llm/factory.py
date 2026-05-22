"""Provider-class construction via a registry. Adding a provider = one entry.

Lazy imports keep optional provider deps off the import path.
"""

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from langchain_core.language_models import BaseChatModel

from docspatch.llm.catalogue import resolve_tier_model
from docspatch.types.llm import Provider, as_provider

KwargsMapper = Callable[[str, str, int | None], dict[str, Any]]
"""Maps ``(model, api_key, max_tokens)`` to one provider's constructor kwargs."""


def _standard_kwargs(model_key: str) -> KwargsMapper:
    """Build a mapper for providers that take ``api_key`` + ``max_tokens`` verbatim."""

    def mapper(model: str, api_key: str, max_tokens: int | None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {model_key: model, "api_key": api_key}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        return kwargs

    return mapper


def _gemini_kwargs(model: str, api_key: str, max_tokens: int | None) -> dict[str, Any]:
    """Gemini uses ``google_api_key`` and ``max_output_tokens``."""
    kwargs: dict[str, Any] = {"model": model, "google_api_key": api_key}
    if max_tokens is not None:
        kwargs["max_output_tokens"] = max_tokens
    return kwargs


@dataclass(frozen=True)
class ProviderSpec:
    """How to import and construct one provider's chat model."""

    module: str
    class_name: str
    kwargs_mapper: KwargsMapper


PROVIDERS: dict[Provider, ProviderSpec] = {
    "anthropic": ProviderSpec("langchain_anthropic", "ChatAnthropic", _standard_kwargs("model_name")),
    "openai": ProviderSpec("langchain_openai", "ChatOpenAI", _standard_kwargs("model")),
    "gemini": ProviderSpec("langchain_google_genai", "ChatGoogleGenerativeAI", _gemini_kwargs),
}


def load_provider_class(spec: ProviderSpec) -> type[BaseChatModel]:
    """Import and return the chat model class for ``spec``.

    Raises:
        ImportError: The provider's optional dependency is not installed.
    """
    module = importlib.import_module(spec.module)
    return cast(type[BaseChatModel], getattr(module, spec.class_name))


def build_llm(provider: str, api_key: str, tier: str, max_tokens: int | None = None) -> BaseChatModel:
    """Construct a chat model for ``provider`` at ``tier``."""
    p = as_provider(provider)
    spec = PROVIDERS[p]
    model = resolve_tier_model(p, tier)
    cls = load_provider_class(spec)
    return cls(**spec.kwargs_mapper(model, api_key, max_tokens))


def build_validator_llm(provider: str, api_key: str) -> BaseChatModel:
    """Minimal-token client used only for :meth:`LLMClient.validate_key`."""
    return build_llm(provider, api_key, "fast", max_tokens=1)
