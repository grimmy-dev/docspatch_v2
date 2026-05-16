"""LLMClient deep module behavior tests — mocked LangChain, no real API calls."""

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from docspatch.errors import ConfigError, LLMError
from docspatch.llm_client import TIER_CATALOGUE, LLMClient

PROVIDERS = ["anthropic", "openai", "gemini"]

PATCH_TARGETS = {
    "anthropic": "docspatch.llm_client.ChatAnthropic",
    "openai": "docspatch.llm_client.ChatOpenAI",
    "gemini": "docspatch.llm_client.ChatGoogleGenerativeAI",
}


@dataclass
class SampleSchema:
    answer: str


def make_client(provider: str, tier: str = "balanced") -> LLMClient:
    with patch(PATCH_TARGETS[provider]):
        return LLMClient(provider=provider, api_key="fake-key", generator_tier=tier)


# --- tier catalogue ---


def test_tier_catalogue_has_all_providers():
    assert set(TIER_CATALOGUE.keys()) == {"anthropic", "openai", "gemini"}


def test_tier_catalogue_each_provider_has_all_tiers():
    for provider in PROVIDERS:
        tiers = {t.tier for t in TIER_CATALOGUE[provider]}
        assert tiers == {"fast", "balanced", "best"}, f"{provider} missing tiers"


def test_tier_catalogue_entries_have_model_and_prices():
    for provider, entries in TIER_CATALOGUE.items():
        for entry in entries:
            assert entry.model, f"{provider}/{entry.tier}: missing model name"
            assert entry.price_input_per_1m > 0
            assert entry.price_output_per_1m > 0


# --- instantiation ---


@pytest.mark.parametrize("provider", PROVIDERS)
def test_instantiates_for_each_provider(provider):
    with patch(PATCH_TARGETS[provider]):
        client = LLMClient(provider=provider, api_key="fake-key")
    assert client.provider == provider


def test_invalid_provider_raises_config_error():
    with pytest.raises(ConfigError):
        LLMClient(provider="llama", api_key="fake")


# --- model slots ---


@pytest.mark.parametrize("provider", PROVIDERS)
def test_scout_model_is_fast_tier(provider):
    client = make_client(provider)
    fast = next(t.model for t in TIER_CATALOGUE[provider] if t.tier == "fast")
    assert client.scout_model == fast


@pytest.mark.parametrize("provider", PROVIDERS)
def test_generator_model_defaults_to_balanced(provider):
    client = make_client(provider)
    balanced = next(t.model for t in TIER_CATALOGUE[provider] if t.tier == "balanced")
    assert client.generator_model == balanced


@pytest.mark.parametrize("provider", PROVIDERS)
def test_generator_model_respects_tier_override(provider):
    client = make_client(provider, tier="best")
    best = next(t.model for t in TIER_CATALOGUE[provider] if t.tier == "best")
    assert client.generator_model == best


# --- validate_key ---


def test_validate_key_returns_true_on_valid_call():
    with patch(PATCH_TARGETS["anthropic"]) as mock_cls:
        mock_llm = MagicMock()
        mock_cls.return_value = mock_llm
        mock_llm.invoke.return_value = MagicMock(content="ok")
        client = LLMClient(provider="anthropic", api_key="sk-ant-valid")
    assert client.validate_key() is True


def test_validate_key_returns_false_on_auth_error():
    with patch(PATCH_TARGETS["anthropic"]) as mock_cls:
        mock_llm = MagicMock()
        mock_cls.return_value = mock_llm
        mock_llm.invoke.side_effect = Exception("401 Unauthorized")
        client = LLMClient(provider="anthropic", api_key="sk-ant-bad")
    assert client.validate_key() is False


# --- with_structured_output ---


@pytest.mark.parametrize("provider", PROVIDERS)
def test_with_structured_output_delegates_to_llm(provider):
    mock_llm = MagicMock()
    mock_chain = MagicMock()
    mock_llm.with_structured_output.return_value = mock_chain

    with patch(PATCH_TARGETS[provider]) as mock_cls:
        mock_cls.return_value = mock_llm
        client = LLMClient(provider=provider, api_key="fake-key")

    result = client.with_structured_output(SampleSchema)
    mock_llm.with_structured_output.assert_called_once_with(SampleSchema)
    assert result is mock_chain


# --- invoke + error wrapping ---


def test_invoke_returns_content_string():
    with patch(PATCH_TARGETS["anthropic"]) as mock_cls:
        mock_llm = MagicMock()
        mock_cls.return_value = mock_llm
        mock_llm.invoke.return_value = MagicMock(content="hello")
        client = LLMClient(provider="anthropic", api_key="fake-key")

    assert client.invoke("prompt") == "hello"


def test_invoke_raises_llm_error_on_non_transient():
    with patch(PATCH_TARGETS["anthropic"]) as mock_cls:
        mock_llm = MagicMock()
        mock_cls.return_value = mock_llm
        mock_llm.invoke.side_effect = Exception("context_length_exceeded")
        client = LLMClient(provider="anthropic", api_key="fake-key")

    with pytest.raises(LLMError):
        client.invoke("too long prompt")


def test_invoke_retries_on_transient_error(monkeypatch):
    monkeypatch.setattr("docspatch.llm_client.RETRY_DELAY", 0.0)

    with patch(PATCH_TARGETS["anthropic"]) as mock_cls:
        mock_llm = MagicMock()
        mock_cls.return_value = mock_llm
        mock_llm.invoke.side_effect = [
            Exception("rate_limit exceeded"),
            MagicMock(content="ok"),
        ]
        client = LLMClient(provider="anthropic", api_key="fake-key")

    assert client.invoke("prompt") == "ok"
    assert mock_llm.invoke.call_count == 2


def test_invoke_raises_llm_error_after_all_retries_exhausted(monkeypatch):
    monkeypatch.setattr("docspatch.llm_client.RETRY_DELAY", 0.0)

    with patch(PATCH_TARGETS["anthropic"]) as mock_cls:
        mock_llm = MagicMock()
        mock_cls.return_value = mock_llm
        mock_llm.invoke.side_effect = Exception("429 rate_limit")
        client = LLMClient(provider="anthropic", api_key="fake-key")

    with pytest.raises(LLMError):
        client.invoke("prompt")
