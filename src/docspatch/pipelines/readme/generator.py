"""Draft and refine README documents by wrapping LLM execution in quality validation rules."""

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
        """Generate a markdown README and calculate the token usage incurred during execution.

        Args:
            pre: The contextual pre-context mapping repo metadata and tree structure.
            woven: The aggregated code context gathered during code drill.
            existing_readme: The current README content of the repository if present.
            feedback: Refinement suggestions collected from prior rounds.

        Returns:
            A tuple pairing the output markdown string and token consumption statistics.
        """
        ...


class LLMReadmeGenerator:
    """LLM-backed generator: one call, plus one auto-revision if a quality check trips."""

    def __init__(self, client: LLMClient) -> None:
        """Initialize the generator with an LLM client structured around the README output schema.

        Args:
            client: The LLM client interface utilized for generation.
        """
        self.chain = client.with_structured_output(ReadmeOutput)

    async def generate(
        self, *, pre: PreContext, woven: str, existing_readme: str | None, feedback: str | None
    ) -> tuple[str, TokenUsage]:
        """Draft a README and execute automated revisions if structured findings reveal quality issues.

        Args:
            pre: The contextual pre-context mapping repo metadata.
            woven: The codebase context compiled during triage and drill phases.
            existing_readme: The preexisting repository README, or null.
            feedback: Constructive feedback from prior generations.

        Returns:
            A tuple consisting of the final markdown draft and cumulative token usage.
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
