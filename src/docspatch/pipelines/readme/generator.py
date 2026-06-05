"""Single-call README generator with a deterministic quality-gate auto-revision."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from docspatch.llm import TokenUsage
from docspatch.pipelines.readme.prompts import build_generator_prompt
from docspatch.pipelines.readme.quality import findings_as_feedback, inspect_readme
from docspatch.pipelines.readme.state import PreContext
from docspatch.schemas import ReadmeOutput
from docspatch.utils.logging import get_logger

if TYPE_CHECKING:
    from docspatch.llm import LLMClient

log = get_logger("readme.generator")

REVISE_LIMIT = 1
"""Max deterministic-gate auto-revisions before the draft reaches the reviewer."""


class ReadmeGenerator(Protocol):
    """What the README pipeline needs from a generator."""

    async def generate(
        self, *, pre: PreContext, woven: str, existing_readme: str | None, feedback: str | None
    ) -> tuple[str, TokenUsage]:
        """Produce a README and report the tokens its calls consumed.

        Args:
            pre: The run backbone (scope, facts, entry points).
            woven: The assembled context the README is grounded in.
            existing_readme: The current README, or null for a first write.
            feedback: Accumulated revise feedback, or null.

        Returns:
            The README markdown and the total token usage.
        """
        ...


class LLMReadmeGenerator:
    """LLM-backed generator: one call, plus one auto-revision if a quality check trips."""

    def __init__(self, client: LLMClient) -> None:
        """Bind the generator to a structured-output client.

        Args:
            client: The LLM client used for every call.
        """
        self.chain = client.with_structured_output(ReadmeOutput)

    async def generate(
        self, *, pre: PreContext, woven: str, existing_readme: str | None, feedback: str | None
    ) -> tuple[str, TokenUsage]:
        """Draft the README, then auto-revise once if it trips a quality check.

        The deterministic gate keeps obvious defects (marketing language, a
        missing title, an unnamed project, a missing entry-point command) from
        reaching the reviewer, so the manual revise loop is left for polish.

        Args:
            pre: The run backbone.
            woven: The assembled context.
            existing_readme: The current README, or null.
            feedback: Accumulated revise feedback, or null.

        Returns:
            The README markdown and the total token usage across every call.
        """
        result, usage = await self.chain.ainvoke(build_generator_prompt(pre.scope, woven, existing_readme, feedback))
        markdown = result.markdown
        name = pre.facts.name if pre.facts else None
        for _ in range(REVISE_LIMIT):
            findings = inspect_readme(markdown, project_name=name, entry_points=pre.entry_points)
            if not findings:
                break
            log.debug("quality gate: revising for %s", ", ".join(f.code for f in findings))
            gate = findings_as_feedback(findings)
            combined = f"{feedback}\n{gate}" if feedback else gate
            result, revise_usage = await self.chain.ainvoke(build_generator_prompt(pre.scope, woven, existing_readme, combined))
            markdown, usage = result.markdown, usage + revise_usage
        return markdown, usage
