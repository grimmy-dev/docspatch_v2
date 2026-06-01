"""Manage dynamic instantiation of LLM model providers."""

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from langchain_core.language_models import BaseChatModel

from docspatch.llm.catalogue import resolve_tier_model
from docspatch.schemas import Provider, as_provider

KwargsMapper = Callable[[str, str, int | None], dict[str, Any]]
"""Maps ``(model, api_key, max_tokens)`` to one provider's constructor kwargs."""


def _standard_kwargs(model_key: str) -> KwargsMapper:
    """Create a mapper for providers using standard argument naming conventions.

    Args:
        model_key: Key identifier for the model argument.

    Returns:
        Kwargs mapping function.
    """

    def mapper(model: str, api_key: str, max_tokens: int | None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {model_key: model, "api_key": api_key}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        return kwargs

    return mapper


def _gemini_kwargs(model: str, api_key: str, max_tokens: int | None) -> dict[str, Any]:
    """Transform parameters to match the Gemini provider expectation.

    Returns:
        Dictionary of provider-specific keywords.
    """
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
    """Dynamically load and return the chat model class specified in the provider definition.

    Args:
        spec: Provider specification.

    Returns:
        Chat model class.

    Raises:
        ImportError: Dependencies are missing.
    """
    module = importlib.import_module(spec.module)
    return cast(type[BaseChatModel], getattr(module, spec.class_name))


def build_llm(provider: str, api_key: str, tier: str, max_tokens: int | None = None) -> BaseChatModel:
    """Instantiate a chat model for a given provider and tier.

    Args:
        provider: Target provider.
        api_key: Authentication key.
        tier: Performance tier.

    Returns:
        Configured chat model instance.
    """
    p = as_provider(provider)
    spec = PROVIDERS[p]
    model = resolve_tier_model(p, tier)
    cls = load_provider_class(spec)
    return cls(**spec.kwargs_mapper(model, api_key, max_tokens))


def build_validator_llm(provider: str, api_key: str) -> BaseChatModel:
    """Create a lightweight client instance for rapid key validation.

    Returns:
        Fast chat model instance.
    """
    return build_llm(provider, api_key, "fast", max_tokens=1)
