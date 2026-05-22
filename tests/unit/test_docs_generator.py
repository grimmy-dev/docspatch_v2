"""Generator behaviors: anti-LLM-ese silent retry (capped at 2 attempts)."""

import asyncio
from dataclasses import dataclass

from docspatch.llm import TokenUsage
from docspatch.pipelines.docs.generator import LLMDocstringGenerator
from docspatch.pipelines.docs.prompts import DocstringItem


@dataclass
class FakeChain:
    """Stub chain returning queued docstring maps per ainvoke call."""

    responses: list[dict[str, str]]
    calls: list[str]

    async def ainvoke(self, prompt: str) -> object:
        self.calls.append(prompt)
        payload = self.responses.pop(0)

        class Result:
            docstrings = payload

        return Result(), TokenUsage(10, 3)


def make_generator(
    responses: list[dict[str, str]], remarks: str | None = None
) -> tuple[LLMDocstringGenerator, FakeChain]:
    chain = FakeChain(responses=responses, calls=[])
    gen = LLMDocstringGenerator.__new__(LLMDocstringGenerator)
    gen.chain = chain  # type: ignore[assignment]
    gen.remarks = remarks
    return gen, chain


def test_remarks_appear_in_generated_prompt() -> None:
    items = [DocstringItem(key="m::f", signature="def f():", body="pass")]
    gen, chain = make_generator([{"m::f": "Return the value."}], remarks="Use British spelling.")
    asyncio.run(gen.generate_batch(items, "concise"))
    assert "Use British spelling." in chain.calls[0]


def test_clean_response_returns_unchanged() -> None:
    items = [DocstringItem(key="m::f", signature="def f():", body="pass")]
    gen, chain = make_generator([{"m::f": "Return the value."}])
    out, _usage = asyncio.run(gen.generate_batch(items, "concise"))
    assert out == {"m::f": "Return the value."}
    assert len(chain.calls) == 1


def test_banned_phrase_triggers_silent_retry_only_for_offending_key() -> None:
    items = [
        DocstringItem(key="m::f", signature="def f():", body="pass"),
        DocstringItem(key="m::g", signature="def g():", body="pass"),
    ]
    gen, chain = make_generator(
        [
            {"m::f": "This function does x.", "m::g": "Return y."},
            {"m::f": "Do x."},
        ]
    )
    out, _usage = asyncio.run(gen.generate_batch(items, "concise"))
    assert out == {"m::f": "Do x.", "m::g": "Return y."}
    assert len(chain.calls) == 2
    # second call should not include the clean key
    assert "m::g" not in chain.calls[1]
    assert "m::f" in chain.calls[1]


def test_banned_phrase_retry_caps_at_two_extra_attempts() -> None:
    items = [DocstringItem(key="m::f", signature="def f():", body="pass")]
    gen, chain = make_generator(
        [
            {"m::f": "This function x."},
            {"m::f": "Simply x."},
            {"m::f": "Basically x."},
        ]
    )
    out, _usage = asyncio.run(gen.generate_batch(items, "concise"))
    # surfaces final string even though still banned — caller-side review handles
    assert out == {"m::f": "Basically x."}
    assert len(chain.calls) == 3
