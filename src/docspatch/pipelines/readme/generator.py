"""LLM-powered README generation: one call when it fits, a refine fold when it overflows."""

from dataclasses import replace
from typing import Protocol

from docspatch.llm import LLMClient, TokenUsage
from docspatch.pipelines.readme.markers import FileBlock
from docspatch.pipelines.readme.prompts import (
    ReadmeContext,
    build_refine_prompt,
    build_single_prompt,
)
from docspatch.pipelines.readme.quality import findings_as_feedback, inspect_readme
from docspatch.schemas import ReadmeOutput
from docspatch.source import estimate_tokens
from docspatch.utils.batcher import BatchPlan, greedy_batches
from docspatch.utils.logging import get_logger

log = get_logger("readme.generator")

REVISE_LIMIT = 1
"""Max deterministic-gate auto-revisions before the draft goes to review regardless."""


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
    """LLM-backed generator: one call under the limit, a refine fold above it."""

    def __init__(self, client: LLMClient, *, batch_token_limit: int) -> None:
        """Bind the generator to a client and its per-batch token budget.

        Args:
            client: The LLM client used for every call.
            batch_token_limit: The token budget that triggers the refine fold.
        """
        self.chain = client.with_structured_output(ReadmeOutput)
        self.batch_token_limit = batch_token_limit

    async def generate(self, ctx: ReadmeContext, blocks: list[FileBlock]) -> tuple[str, TokenUsage]:
        """Draft the README, then auto-revise once if it trips a quality check.

        The deterministic gate keeps obvious defects (marketing language, a
        missing title, an unnamed project) from ever reaching the reviewer, so
        the manual revise loop is left for polish rather than repair.

        Args:
            ctx: Resolved facts, tree, and instructions for the run.
            blocks: The in-scope file-summary blocks.

        Returns:
            The README markdown and the total token usage across every call.
        """
        markdown, usage = await self._draft(ctx, blocks)
        for _ in range(REVISE_LIMIT):
            findings = inspect_readme(markdown, ctx)
            if not findings:
                break
            log.debug("quality gate: revising for %s", ", ".join(f.code for f in findings))
            ctx = replace(ctx, feedback=(*ctx.feedback, findings_as_feedback(findings)))
            markdown, revise_usage = await self._draft(ctx, blocks)
            usage += revise_usage
        return markdown, usage

    async def _draft(self, ctx: ReadmeContext, blocks: list[FileBlock]) -> tuple[str, TokenUsage]:
        """Produce one README draft, folding batch by batch only when blocks overflow.

        The first batch seeds a full draft with the backbone; each later batch
        revises that draft, again carrying the backbone, so no step ever drafts
        without the project's identity.

        Args:
            ctx: Resolved facts, tree, and instructions for the run.
            blocks: The in-scope file-summary blocks.

        Returns:
            The README markdown and the token usage for this draft.
        """
        batches = partition(blocks, self.batch_token_limit).batches
        if len(batches) <= 1:
            log.debug("single-call generation: %d block(s)", len(blocks))
            result, usage = await self.chain.ainvoke(build_single_prompt(ctx, blocks))
            return result.markdown, usage

        log.debug("refine-fold generation: %d block(s) over %d batch(es)", len(blocks), len(batches))
        seed, *rest = batches
        result, usage = await self.chain.ainvoke(build_single_prompt(ctx, list(seed.items)))
        draft = result.markdown
        for batch in rest:
            revised, step_usage = await self.chain.ainvoke(build_refine_prompt(ctx, draft, list(batch.items)))
            draft, usage = revised.markdown, usage + step_usage
        return draft, usage
