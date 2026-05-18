"""LLM facade: catalogue, factory, client. Single import point for callers.

Type narrowers (``as_provider`` / ``as_tier``) live in :mod:`docspatch.types.llm`
next to the literals they narrow — import them there.
"""

from docspatch.llm.catalogue import TIER_CATALOGUE, TierInfo, resolve_tier_model, tier_info
from docspatch.llm.client import LLM_RETRY, LLMClient, RetryingChain, is_transient
from docspatch.llm.factory import PROVIDER_MODULES, build_llm, build_validator_llm, load_provider_class

__all__ = [
    "LLM_RETRY",
    "LLMClient",
    "PROVIDER_MODULES",
    "RetryingChain",
    "TIER_CATALOGUE",
    "TierInfo",
    "build_llm",
    "build_validator_llm",
    "is_transient",
    "load_provider_class",
    "resolve_tier_model",
    "tier_info",
]
