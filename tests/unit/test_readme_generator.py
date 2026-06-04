"""README generator: partition coverage and single vs refine-fold dispatch."""

import pytest

from docspatch.llm import TokenUsage
from docspatch.pipelines.readme.generator import LLMReadmeGenerator, partition
from docspatch.pipelines.readme.markers import FileBlock
from docspatch.pipelines.readme.prompts import ReadmeContext
from docspatch.schemas import ReadmeOutput


def _blocks(n, body="word " * 20):
    return [FileBlock(path=f"src/d{i}/m{i}.py", body=f"## m{i}.py\n{body}") for i in range(n)]


def _ctx():
    return ReadmeContext(scope=".", dir_tree="src")


def _ctx_with_identity():
    from docspatch.utils.project import ProjectFacts

    return ReadmeContext(scope=".", dir_tree="src", facts=ProjectFacts(name="demo"))


class _FakeChain:
    def __init__(self):
        self.prompts: list[str] = []

    async def ainvoke(self, prompt):
        self.prompts.append(prompt)
        # A valid titled README so the deterministic quality gate stays quiet and
        # these tests measure only partition + dispatch, not auto-revision.
        return ReadmeOutput(markdown=f"# Title\n\nDOC{len(self.prompts)}"), TokenUsage(10, 5)


class _FakeClient:
    def __init__(self, chain):
        self._chain = chain

    def with_structured_output(self, schema):
        return self._chain


def test_partition_covers_every_block():
    blocks = _blocks(12)
    plan = partition(blocks, limit=50)
    seen = [b.path for batch in plan.batches for b in batch.items]
    assert sorted(seen) == sorted(b.path for b in blocks)
    assert plan.batch_count > 1  # the slice exceeds one batch


def test_partition_single_batch_when_small():
    plan = partition(_blocks(2), limit=100_000)
    assert plan.batch_count == 1


@pytest.mark.asyncio
async def test_single_call_under_limit():
    chain = _FakeChain()
    gen = LLMReadmeGenerator(_FakeClient(chain), batch_token_limit=100_000)
    markdown, usage = await gen.generate(_ctx(), _blocks(3))
    assert "DOC1" in markdown
    assert len(chain.prompts) == 1
    assert usage == TokenUsage(10, 5)


@pytest.mark.asyncio
async def test_refine_fold_above_limit_sums_usage():
    chain = _FakeChain()
    gen = LLMReadmeGenerator(_FakeClient(chain), batch_token_limit=50)
    blocks = _blocks(12)
    plan = partition(blocks, limit=50)
    markdown, usage = await gen.generate(_ctx(), blocks)
    # One seed call plus one refine call per remaining batch — no separate reduce.
    assert len(chain.prompts) == plan.batch_count
    assert usage == TokenUsage(10 * plan.batch_count, 5 * plan.batch_count)
    assert f"DOC{plan.batch_count}" in markdown


@pytest.mark.asyncio
async def test_refine_fold_carries_identity_in_every_step():
    chain = _FakeChain()
    gen = LLMReadmeGenerator(_FakeClient(chain), batch_token_limit=50)
    blocks = _blocks(12)
    await gen.generate(_ctx_with_identity(), blocks)
    assert len(chain.prompts) > 1
    assert all("Project name: demo" in p for p in chain.prompts)


class _TitlelessThenFixed:
    """First draft trips the gate (no title); the revise call returns a valid one."""

    def __init__(self):
        self.prompts: list[str] = []

    async def ainvoke(self, prompt):
        self.prompts.append(prompt)
        body = "no title here" if len(self.prompts) == 1 else "# Title\n\nfixed"
        return ReadmeOutput(markdown=body), TokenUsage(10, 5)


@pytest.mark.asyncio
async def test_quality_gate_auto_revises_a_flagged_draft():
    chain = _TitlelessThenFixed()
    gen = LLMReadmeGenerator(_FakeClient(chain), batch_token_limit=100_000)
    markdown, usage = await gen.generate(_ctx(), _blocks(2))
    assert markdown == "# Title\n\nfixed"
    assert len(chain.prompts) == 2  # initial draft + one auto-revision
    assert usage == TokenUsage(20, 10)
    # The revise call carries the gate's finding as feedback.
    assert "title" in chain.prompts[1].lower()


@pytest.mark.asyncio
async def test_quality_gate_revision_is_bounded():
    # A chain that never adds a title must not loop past the revise limit.
    chain = _FakeChain()

    async def titleless(prompt):
        chain.prompts.append(prompt)
        return ReadmeOutput(markdown="still no title"), TokenUsage(10, 5)

    chain.ainvoke = titleless  # type: ignore[method-assign]
    gen = LLMReadmeGenerator(_FakeClient(chain), batch_token_limit=100_000)
    markdown, _ = await gen.generate(_ctx(), _blocks(2))
    assert markdown == "still no title"
    assert len(chain.prompts) == 2  # initial + exactly REVISE_LIMIT(=1) retry
