"""Tier × model × price catalogue. Single source of truth for what each provider offers."""

from dataclasses import dataclass

from docspatch.schemas import Provider, Tier, as_provider, as_tier
from docspatch.utils.errors import ConfigError


@dataclass(frozen=True)
class TierInfo:
    tier: Tier
    model: str
    price_input_per_1m: float
    price_output_per_1m: float
    icon: str = ""


TIER_CATALOGUE: dict[Provider, list[TierInfo]] = {
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
        TierInfo("balanced", "gemini-3-flash-preview", 0.50, 3.00, "⚖️"),
        TierInfo("best", "gemini-3.1-pro-preview", 2.00, 12.00, "🏆"),
    ],
}


def tier_info(provider: str, tier: str) -> TierInfo:
    """Look up a :class:`TierInfo` or raise :class:`ConfigError` on unknown pair."""
    p, t = as_provider(provider), as_tier(tier)
    for entry in TIER_CATALOGUE[p]:
        if entry.tier == t:
            return entry
    raise ConfigError.unknown_tier(tier)


def resolve_tier_model(provider: str, tier: str) -> str:
    """Return the model string for ``(provider, tier)``."""
    return tier_info(provider, tier).model


def tier_for_model(provider: str, model: str) -> Tier:
    """Reverse-lookup the tier that owns ``model`` under ``provider``.

    Raises:
        ConfigError: When ``model`` is not in the catalogue for ``provider``.
    """
    p = as_provider(provider)
    for entry in TIER_CATALOGUE[p]:
        if entry.model == model:
            return entry.tier
    raise ConfigError.unknown_tier(model)
