"""LLMClient deep module behavior tests — mocked LangChain, no real API calls."""

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from docspatch.llm import TIER_CATALOGUE, LLMClient, RetryingChain
from docspatch.types.llm import as_provider
from docspatch.utils.errors import ConfigError, LLMError

PROVIDERS = ["anthropic", "openai", "gemini"]

PATCH_TARGETS = {
    "anthropic": "langchain_anthropic.ChatAnthropic",
    "openai": "langchain_openai.ChatOpenAI",
    "gemini": "langchain_google_genai.ChatGoogleGenerativeAI",
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
        tiers = {t.tier for t in TIER_CATALOGUE[as_provider(provider)]}
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


def test_validate_key_uses_minimal_token_call():
    """The validation path must use max_tokens=1 to keep latency in milliseconds."""
    with patch(PATCH_TARGETS["anthropic"]) as mock_cls:
        mock_cls.return_value.invoke.return_value = MagicMock(content="x")
        client = LLMClient(provider="anthropic", api_key="sk-ant-valid")
        client.validate_key()
        # Last constructor call is the validator client — it must pass max_tokens=1.
        last_kwargs = mock_cls.call_args_list[-1].kwargs
        assert last_kwargs.get("max_tokens") == 1


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
    assert isinstance(result, RetryingChain)
    assert result._chain is mock_chain


# --- RetryingChain async retry + error wrapping ---


def test_retrying_chain_returns_value_on_success():
    import asyncio
    from unittest.mock import AsyncMock

    from docspatch.llm import RetryingChain

    chain = MagicMock()
    chain.ainvoke = AsyncMock(return_value="ok")
    rc = RetryingChain(chain)
    assert asyncio.run(rc.ainvoke("prompt")) == "ok"


def test_retrying_chain_retries_transient(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock

    from docspatch.llm import RetryingChain
    from docspatch.utils.retry import RetryPolicy

    monkeypatch.setattr("docspatch.llm.client.LLM_RETRY", RetryPolicy(max_attempts=3, base_delay=0.0))
    chain = MagicMock()
    chain.ainvoke = AsyncMock(side_effect=[Exception("rate_limit"), "ok"])
    rc = RetryingChain(chain)
    assert asyncio.run(rc.ainvoke("prompt")) == "ok"
    assert chain.ainvoke.await_count == 2


def test_retrying_chain_wraps_non_transient_as_llm_error():
    import asyncio
    from unittest.mock import AsyncMock

    from docspatch.llm import RetryingChain

    chain = MagicMock()
    chain.ainvoke = AsyncMock(side_effect=Exception("context_length_exceeded"))
    rc = RetryingChain(chain)
    with pytest.raises(LLMError):
        asyncio.run(rc.ainvoke("prompt"))


def test_retrying_chain_wraps_exhaustion_as_llm_error(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock

    from docspatch.llm import RetryingChain
    from docspatch.utils.retry import RetryPolicy

    monkeypatch.setattr("docspatch.llm.client.LLM_RETRY", RetryPolicy(max_attempts=3, base_delay=0.0))
    chain = MagicMock()
    chain.ainvoke = AsyncMock(side_effect=Exception("429 rate_limit"))
    rc = RetryingChain(chain)
    with pytest.raises(LLMError):
        asyncio.run(rc.ainvoke("prompt"))
