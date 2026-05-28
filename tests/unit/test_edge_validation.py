"""Zero-trust at edges: external inputs validated, fail fast with named errors."""

import pytest

from docspatch.llm import LLMClient
from docspatch.llm.pricing import actual_cost, estimate_cost
from docspatch.schemas import as_provider, as_tier
from docspatch.utils.errors import ConfigError


def test_unknown_provider_raises_named_error() -> None:
    with pytest.raises(ConfigError, match="Unknown provider"):
        as_provider("nope")


def test_unknown_tier_raises_named_error() -> None:
    with pytest.raises(ConfigError, match="Unknown tier"):
        as_tier("turbo")


def test_llm_client_rejects_empty_api_key() -> None:
    with pytest.raises(ConfigError, match="No API key"):
        LLMClient(provider="anthropic", api_key="")


def test_llm_client_rejects_whitespace_api_key() -> None:
    with pytest.raises(ConfigError, match="No API key"):
        LLMClient(provider="anthropic", api_key="   ")


def test_estimate_cost_rejects_negative_tokens() -> None:
    with pytest.raises(ConfigError, match="must be ≥ 0"):
        estimate_cost("anthropic", "fast", -1)


def test_actual_cost_rejects_negative_tokens() -> None:
    with pytest.raises(ConfigError, match="must be ≥ 0"):
        actual_cost("anthropic", "fast", 10, -5)
