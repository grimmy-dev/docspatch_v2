"""LLM facade: catalogue, factory, client. Single import point for callers.

Type narrowers (``as_provider`` / ``as_tier``) live in :mod:`docspatch.types.llm`
next to the literals they narrow — import them there.
"""

from docspatch.llm.catalogue import TIER_CATALOGUE, TierInfo, resolve_tier_model, tier_for_model, tier_info
from docspatch.llm.client import LLM_RETRY, LLMClient, is_transient
from docspatch.llm.factory import PROVIDERS, ProviderSpec, build_llm, build_validator_llm
from docspatch.llm.runnable import TokenUsage, TypedRunnable

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
]
