"""Provide protocols and concrete implementations for automated docstring generation using LLMs."""

from typing import Protocol

from docspatch.llm import LLMClient, TokenUsage
from docspatch.pipelines.docs.prompts import (
    DocstringItem,
    build_batch_docstring_prompt,
    needs_rewrite,
)
from docspatch.pipelines.docs.render import render_google_docstring
from docspatch.schemas import BatchDocstringOutput

RETRY_LIMIT = 2
"""Max silent retries for keys the model omitted or filled with a banned phrase."""

RETRY_NOTE = "Previous draft was vague or used banned wording. Rewrite: lead with a concrete verb and name what it actually does."


def with_retry_note(item: DocstringItem, flagged: bool) -> DocstringItem:
    """Append the style-rewrite note to a flagged item, leaving omitted ones unchanged.

    Args:
        item: The item being retried.
        flagged: Whether its prior draft tripped a style guardrail.

    Returns:
        The item with the rewrite note added when flagged, else the item itself.
    """
    if not flagged:
        return item
    return item.model_copy(update={"feedback": (*item.feedback, RETRY_NOTE)})


class DocstringGenerator(Protocol):
    """What the docs pipeline needs from a generator.

    The pipeline owns ``remarks``: it assigns the resolved run-wide instruction
    after restoring it from checkpoint metadata, so the attribute is writable.
    """

    remarks: str | None

    async def generate_batch(self, items: list[DocstringItem], tone: str) -> tuple[dict[str, str], TokenUsage]:
        """Return a mapping of identifiers to generated docstrings along with total token usage.

        Args:
            items: List of docstring tasks to perform.
            tone: Style guide instructions for the output.

        Returns:
            Pair containing a map of IDs to text and the token consumption metrics.
        """
        ...


class LLMDocstringGenerator:
    """LLM-backed batch generator with banned-phrase silent retry.

    ``remarks`` is a run-wide instruction injected into every prompt. It is held
    here, not in graph state, so a resumed run restores it from checkpoint
    metadata rather than carrying it through the checkpointer.
    """

    def __init__(self, client: LLMClient, remarks: str | None = None) -> None:
        """Initialize a generator instance with a provided language model client.

        Args:
            client: LLM client instance for generating documentation strings.
            remarks: Optional custom instructions to guide the model behavior.
        """
        self.chain = client.with_structured_output(BatchDocstringOutput)
        self.remarks = remarks

    async def generate_batch(self, items: list[DocstringItem], tone: str) -> tuple[dict[str, str], TokenUsage]:
        """Generate rendered docstrings for items, retrying omitted or banned-phrase keys.

        Args:
            items: The list of items requiring docstrings.
            tone: The requested tone for the generated text.

        Returns:
            A mapping of id to rendered Google-style docstring text and the total token usage.
        """
        by_key = {item.key: item for item in items}
        result, usage = await self.chain.ainvoke(build_batch_docstring_prompt(items, tone, self.remarks))
        rendered = {k: render_google_docstring(v) for k, v in result.docstrings.items()}

        # Bounded — a model that keeps omitting a key or repeating a banned phrase
        # exits at the cap; the key stays absent and lands in the review queue.
        # Flagged keys carry a feedback note so the retry corrects the draft rather
        # than re-rolling the identical prompt.
        for _ in range(RETRY_LIMIT):
            missing = {k for k in by_key if k not in rendered}
            flagged = {k for k, v in rendered.items() if needs_rewrite(v)}
            retry_keys = (missing | flagged) & by_key.keys()
            if not retry_keys:
                break
            retry_items = [with_retry_note(by_key[k], k in flagged) for k in retry_keys]
            retry_result, retry_usage = await self.chain.ainvoke(
                build_batch_docstring_prompt(retry_items, tone, self.remarks)
            )
            usage += retry_usage
            for key, value in retry_result.docstrings.items():
                rendered[key] = render_google_docstring(value)
        return rendered, usage
