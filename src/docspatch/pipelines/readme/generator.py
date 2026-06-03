"""LLM-powered README generation using map-reduce partitioning for large codebases."""

from typing import Protocol

from docspatch.llm import LLMClient, TokenUsage
from docspatch.pipelines.readme.markers import FileBlock
from docspatch.pipelines.readme.prompts import (
    ReadmeContext,
    build_map_prompt,
    build_reduce_prompt,
    build_single_prompt,
)
from docspatch.schemas import ReadmeOutput
from docspatch.source import estimate_tokens
from docspatch.utils.batcher import BatchPlan, greedy_batches
from docspatch.utils.logging import get_logger

log = get_logger("readme.generator")


def partition(blocks: list[FileBlock], limit: int) -> BatchPlan[FileBlock]:
    """Split file blocks into token-bounded batches, preserving directory order.

    Args:
        blocks: The in-scope file-summary blocks, in summary order.
        limit: The per-batch token budget.

    Returns:
        A plan whose batches together cover every input block.
    """
    return greedy_batches(blocks, lambda b: estimate_tokens(b.body), limit)


class ReadmeGenerator(Protocol):
    """What the README pipeline needs from a generator."""

    async def generate(self, ctx: ReadmeContext, blocks: list[FileBlock]) -> tuple[str, TokenUsage]:
        """Produce a README and report the tokens its calls consumed.

        Args:
            ctx: Resolved facts, tree, and instructions for the run.
            blocks: The in-scope file-summary blocks.

        Returns:
            The README markdown and the total token usage.
        """
        ...


class LLMReadmeGenerator:
    """LLM-backed generator: one call under the limit, map-reduce above it."""

    def __init__(self, client: LLMClient, *, batch_token_limit: int) -> None:
        """Bind the generator to a client and its per-batch token budget.

        Args:
            client: The LLM client used for every call.
            batch_token_limit: The token budget that triggers map-reduce.
        """
        self.chain = client.with_structured_output(ReadmeOutput)
        self.batch_token_limit = batch_token_limit

    async def generate(self, ctx: ReadmeContext, blocks: list[FileBlock]) -> tuple[str, TokenUsage]:
        """Generate the README, mapping then reducing only when blocks overflow.

        Args:
            ctx: Resolved facts, tree, and instructions for the run.
            blocks: The in-scope file-summary blocks.

        Returns:
            The README markdown and the total token usage.
        """
        plan = partition(blocks, self.batch_token_limit)
        if plan.batch_count <= 1:
            log.debug("single-call generation: %d block(s)", len(blocks))
            result, usage = await self.chain.ainvoke(build_single_prompt(ctx, blocks))
            return result.markdown, usage

        log.debug("map-reduce generation: %d block(s) over %d map batch(es) + reduce", len(blocks), plan.batch_count)
        usage = TokenUsage()
        sections: list[str] = []
        for batch in plan.batches:
            result, batch_usage = await self.chain.ainvoke(build_map_prompt(ctx, list(batch.items)))
            usage += batch_usage
            sections.append(result.markdown)
        merged, reduce_usage = await self.chain.ainvoke(build_reduce_prompt(ctx, sections))
        return merged.markdown, usage + reduce_usage
