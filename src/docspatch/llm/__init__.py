"""Packages the LLM layer, lazy-importing submodules on demand."""

from typing import TYPE_CHECKING

from docspatch.llm.catalogue import TIER_CATALOGUE, TierInfo, resolve_tier_model, tier_for_model, tier_info
from docspatch.llm.usage import TokenUsage

if TYPE_CHECKING:
    from docspatch.llm.client import LLM_RETRY, LLMClient, is_transient, validate_api_key
    from docspatch.llm.factory import PROVIDERS, ProviderSpec, build_llm, build_validator_llm
    from docspatch.llm.runnable import TypedRunnable

# Attribute name -> submodule that defines it. Imported on first access only.
# These pull langchain_core / provider SDKs, so a light import never triggers them.
_LAZY = {
    "LLM_RETRY": "client",
    "LLMClient": "client",
    "is_transient": "client",
    "validate_api_key": "client",
    "PROVIDERS": "factory",
    "ProviderSpec": "factory",
    "build_llm": "factory",
    "build_validator_llm": "factory",
    "TypedRunnable": "runnable",
}

__all__ = [
    "LLM_RETRY",
    "PROVIDERS",
    "LLMClient",
    "ProviderSpec",
    "TIER_CATALOGUE",
    "TierInfo",
    "TokenUsage",
    "TypedRunnable",
    "build_llm",
    "build_validator_llm",
    "is_transient",
    "resolve_tier_model",
    "tier_for_model",
    "tier_info",
    "validate_api_key",
]


def __getattr__(name: str) -> object:
    """Import and return a lazy-loaded symbol from the submodules on first access.

    Args:
        name: The attribute being accessed on the package.

    Returns:
        The requested object from its defining submodule.

    Raises:
        AttributeError: The name is not a known lazy export.
    """
    submodule = _LAZY.get(name)
    if submodule is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module = importlib.import_module(f"docspatch.llm.{submodule}")
    return getattr(module, name)
