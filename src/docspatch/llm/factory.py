"""Contains mapping and setup code to construct LangChain chat model classes."""

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
    """Generate constructor argument mappers for typical LangChain providers.

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
    """Map parameters to Google-specific constructor arguments for Gemini.

    Args:
        model: Model target name.
        api_key: API credential key.
        max_tokens: Token length constraint.

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
    """Import and retrieve the chat model class dynamically from its provider module.

    Args:
        spec: Provider specification.

    Returns:
        Chat model class.
    """
    module = importlib.import_module(spec.module)
    return cast(type[BaseChatModel], getattr(module, spec.class_name))


def build_llm(provider: str, api_key: str, tier: str, max_tokens: int | None = None) -> BaseChatModel:
    """Resolve model specifications and construct the ChatModel class.

    Args:
        provider: Target provider.
        api_key: Authentication key.
        tier: Performance tier.
        max_tokens: Maximum token threshold.

    Returns:
        Configured chat model instance.
    """
    p = as_provider(provider)
    spec = PROVIDERS[p]
    model = resolve_tier_model(p, tier)
    cls = load_provider_class(spec)
    return cls(**spec.kwargs_mapper(model, api_key, max_tokens))


def build_validator_llm(provider: str, api_key: str) -> BaseChatModel:
    """Build a lightweight, token-limited model client for rapid authentication checks.

    Args:
        provider: Target provider.
        api_key: Access credential key.

    Returns:
        Fast chat model instance.
    """
    return build_llm(provider, api_key, "fast", max_tokens=1)
