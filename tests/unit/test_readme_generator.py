"""README generator: partition coverage and single vs map-reduce dispatch."""

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


class _FakeChain:
    def __init__(self):
        self.prompts: list[str] = []

    async def ainvoke(self, prompt):
        self.prompts.append(prompt)
        return ReadmeOutput(markdown=f"DOC{len(self.prompts)}"), TokenUsage(10, 5)


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
    assert markdown == "DOC1"
    assert len(chain.prompts) == 1
    assert usage == TokenUsage(10, 5)


@pytest.mark.asyncio
async def test_map_reduce_above_limit_sums_usage():
    chain = _FakeChain()
    gen = LLMReadmeGenerator(_FakeClient(chain), batch_token_limit=50)
    blocks = _blocks(12)
    plan = partition(blocks, limit=50)
    markdown, usage = await gen.generate(_ctx(), blocks)
    # One call per map batch + one reduce call; usage summed across all.
    assert len(chain.prompts) == plan.batch_count + 1
    assert usage == TokenUsage(10 * (plan.batch_count + 1), 5 * (plan.batch_count + 1))
    assert markdown == f"DOC{plan.batch_count + 1}"
