"""README generator: single-call dispatch and quality-gate auto-revision."""

import pytest

from docspatch.llm import TokenUsage
from docspatch.pipelines.readme.generator import LLMReadmeGenerator
from docspatch.pipelines.readme.state import PreContext
from docspatch.schemas import ReadmeOutput
from docspatch.utils.project import ProjectFacts


def make_pre() -> PreContext:
    return PreContext(
        scope=".",
        tagged_tree="src",
        facts=ProjectFacts(name="demo"),
        dependencies=(),
        entry_points=(),
        entry_point_modules=frozenset(),
        tool_defs="",
    )


class _FakeChain:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def ainvoke(self, prompt: str):  # noqa: ANN201
        self.prompts.append(prompt)
        return ReadmeOutput(markdown=f"# demo\n\nDOC{len(self.prompts)}"), TokenUsage(10, 5)


class _FakeClient:
    def __init__(self, chain) -> None:
        self._chain = chain

    def with_structured_output(self, schema: type):  # noqa: ANN201
        return self._chain


@pytest.mark.asyncio
async def test_single_call_passes_quality_gate() -> None:
    chain = _FakeChain()
    gen = LLMReadmeGenerator(_FakeClient(chain))
    markdown, usage = await gen.generate(pre=make_pre(), woven="ctx", existing_readme=None, feedback=None)
    assert "DOC1" in markdown
    assert len(chain.prompts) == 1
    assert usage == TokenUsage(10, 5)


@pytest.mark.asyncio
async def test_existing_readme_and_feedback_reach_the_prompt() -> None:
    chain = _FakeChain()
    gen = LLMReadmeGenerator(_FakeClient(chain))
    await gen.generate(pre=make_pre(), woven="ctx", existing_readme="# Old\n\nkeep me", feedback="be terse")
    assert "keep me" in chain.prompts[0]
    assert "be terse" in chain.prompts[0]


class _TitlelessThenFixed:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def ainvoke(self, prompt: str):  # noqa: ANN201
        self.prompts.append(prompt)
        body = "no title here" if len(self.prompts) == 1 else "# demo\n\nfixed"
        return ReadmeOutput(markdown=body), TokenUsage(10, 5)


@pytest.mark.asyncio
async def test_quality_gate_auto_revises_a_flagged_draft() -> None:
    chain = _TitlelessThenFixed()
    gen = LLMReadmeGenerator(_FakeClient(chain))
    markdown, usage = await gen.generate(pre=make_pre(), woven="ctx", existing_readme=None, feedback=None)
    assert markdown == "# demo\n\nfixed"
    assert len(chain.prompts) == 2  # initial draft + one auto-revision
    assert usage == TokenUsage(20, 10)
    assert "title" in chain.prompts[1].lower()


@pytest.mark.asyncio
async def test_quality_gate_revision_is_bounded() -> None:
    chain = _FakeChain()

    async def titleless(prompt: str):  # noqa: ANN202
        chain.prompts.append(prompt)
        return ReadmeOutput(markdown="still no title"), TokenUsage(10, 5)

    chain.ainvoke = titleless  # type: ignore[method-assign]
    gen = LLMReadmeGenerator(_FakeClient(chain))
    markdown, _ = await gen.generate(pre=make_pre(), woven="ctx", existing_readme=None, feedback=None)
    assert markdown == "still no title"
    assert len(chain.prompts) == 2  # initial + exactly REVISE_LIMIT(=1) retry
