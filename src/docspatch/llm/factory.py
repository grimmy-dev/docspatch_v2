"""Provider-class construction. Lazy imports keep optional deps off the import path."""

import importlib
from typing import Any, cast

from langchain_core.language_models import BaseChatModel

from docspatch.llm.catalogue import resolve_tier_model
from docspatch.types.llm import Provider, as_provider

PROVIDER_MODULES: dict[Provider, tuple[str, str]] = {
    "anthropic": ("langchain_anthropic", "ChatAnthropic"),
    "openai": ("langchain_openai", "ChatOpenAI"),
    "gemini": ("langchain_google_genai", "ChatGoogleGenerativeAI"),
}


def load_provider_class(provider: str) -> type[BaseChatModel]:
    module_name, class_name = PROVIDER_MODULES[as_provider(provider)]
    module = importlib.import_module(module_name)
    return cast(type[BaseChatModel], getattr(module, class_name))


def provider_kwargs(provider: Provider, model: str, api_key: str, max_tokens: int | None) -> dict[str, Any]:
    """Map normalised args to each provider's kwarg names."""
    if provider == "gemini":
        kwargs: dict[str, Any] = {"model": model, "google_api_key": api_key}
        if max_tokens is not None:
            kwargs["max_output_tokens"] = max_tokens
        return kwargs
    model_key = "model_name" if provider == "anthropic" else "model"
    kwargs = {model_key: model, "api_key": api_key}
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    return kwargs


def build_llm(provider: str, api_key: str, tier: str, max_tokens: int | None = None) -> BaseChatModel:
    p = as_provider(provider)
    model = resolve_tier_model(p, tier)
    cls = load_provider_class(p)
    return cls(**provider_kwargs(p, model, api_key, max_tokens))


def build_validator_llm(provider: str, api_key: str) -> BaseChatModel:
    """Minimal-token client used only for :meth:`LLMClient.validate_key`."""
    return build_llm(provider, api_key, "fast", max_tokens=1)
