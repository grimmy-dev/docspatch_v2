"""LLMClient deep module behavior tests — mocked LangChain, no real API calls."""

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from docspatch.llm import TIER_CATALOGUE, LLMClient, TypedRunnable
from docspatch.schemas import as_provider
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
    assert isinstance(result, TypedRunnable)
    assert result.chain is mock_chain


# --- TypedRunnable async retry + error wrapping ---


def make_gate(max_attempts: int = 3):
    from docspatch.utils.retry import RateLimitGate, RetryPolicy

    return RateLimitGate(RetryPolicy(max_attempts=max_attempts, base_delay=0.0))


def test_retrying_chain_returns_value_on_success():
    import asyncio
    from unittest.mock import AsyncMock

    from docspatch.llm import TypedRunnable

    chain = MagicMock()
    chain.ainvoke = AsyncMock(return_value="ok")
    rc = TypedRunnable(chain, make_gate())
    assert asyncio.run(rc.ainvoke("prompt"))[0] == "ok"


def test_retrying_chain_retries_transient():
    import asyncio
    from unittest.mock import AsyncMock

    from docspatch.llm import TypedRunnable

    chain = MagicMock()
    chain.ainvoke = AsyncMock(side_effect=[Exception("rate_limit"), "ok"])
    rc = TypedRunnable(chain, make_gate())
    assert asyncio.run(rc.ainvoke("prompt"))[0] == "ok"
    assert chain.ainvoke.await_count == 2


def test_retrying_chain_wraps_non_transient_as_llm_error():
    import asyncio
    from unittest.mock import AsyncMock

    from docspatch.llm import TypedRunnable

    chain = MagicMock()
    chain.ainvoke = AsyncMock(side_effect=Exception("context_length_exceeded"))
    rc = TypedRunnable(chain, make_gate())
    with pytest.raises(LLMError):
        asyncio.run(rc.ainvoke("prompt"))


def test_retrying_chain_wraps_exhaustion_as_llm_error():
    import asyncio
    from unittest.mock import AsyncMock

    from docspatch.llm import TypedRunnable

    chain = MagicMock()
    chain.ainvoke = AsyncMock(side_effect=Exception("429 rate_limit"))
    rc = TypedRunnable(chain, make_gate())
    with pytest.raises(LLMError):
        asyncio.run(rc.ainvoke("prompt"))


def test_token_usage_adds_and_totals():
    from docspatch.llm.runnable import TokenUsage, _collected_usage

    summed = TokenUsage(10, 4) + TokenUsage(5, 1)
    assert (summed.input_tokens, summed.output_tokens, summed.total) == (15, 5, 20)

    class FakeHandler:
        usage_metadata = {"m": {"input_tokens": 7, "output_tokens": 2}}

    assert _collected_usage(FakeHandler()) == TokenUsage(7, 2)


# --- TypedRunnable parse-failure retry-once-then-fail ---


def test_typed_runnable_retries_parse_failure_once_then_succeeds():
    import asyncio
    from unittest.mock import AsyncMock

    from langchain_core.exceptions import OutputParserException

    from docspatch.llm import TypedRunnable
    from docspatch.llm.runnable import PARSE_RETRY_SUFFIX

    chain = MagicMock()
    chain.ainvoke = AsyncMock(side_effect=[OutputParserException("bad json"), "ok"])
    rc = TypedRunnable(chain, make_gate())

    assert asyncio.run(rc.ainvoke("prompt"))[0] == "ok"
    assert chain.ainvoke.await_count == 2
    # The second call carries the corrective suffix.
    assert chain.ainvoke.await_args_list[1].args[0].endswith(PARSE_RETRY_SUFFIX)


def test_typed_runnable_raises_parse_failed_after_second_failure():
    import asyncio
    from unittest.mock import AsyncMock

    from langchain_core.exceptions import OutputParserException

    from docspatch.llm import TypedRunnable
    from docspatch.utils.errors import ParseFailed

    chain = MagicMock()
    chain.ainvoke = AsyncMock(side_effect=OutputParserException("still bad"))
    rc = TypedRunnable(chain, make_gate())

    with pytest.raises(ParseFailed) as excinfo:
        asyncio.run(rc.ainvoke("prompt"))
    assert chain.ainvoke.await_count == 2  # exactly one retry, no loop
    assert "still bad" in excinfo.value.raw_output


def test_typed_runnable_treats_pydantic_validation_error_as_parse_failure():
    import asyncio
    from unittest.mock import AsyncMock

    from pydantic import BaseModel

    from docspatch.llm import TypedRunnable
    from docspatch.utils.errors import ParseFailed

    class Schema(BaseModel):
        answer: str

    def raise_validation(*_a, **_kw):
        Schema(answer=123)  # type: ignore[arg-type]  # triggers pydantic ValidationError

    chain = MagicMock()
    chain.ainvoke = AsyncMock(side_effect=raise_validation)
    rc = TypedRunnable(chain, make_gate())

    with pytest.raises(ParseFailed):
        asyncio.run(rc.ainvoke("prompt"))
    assert chain.ainvoke.await_count == 2
