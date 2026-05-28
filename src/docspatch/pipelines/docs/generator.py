"""Batch docstring generator: one LLM call per batch, with anti-LLM-ese retries."""

from typing import Protocol

from docspatch.llm import LLMClient, TokenUsage
from docspatch.pipelines.docs.prompts import (
    DocstringItem,
    build_batch_docstring_prompt,
    contains_banned_phrase,
)
from docspatch.schemas import BatchDocstringOutput

BANNED_RETRY_LIMIT = 2
"""Max silent retries per key when a banned phrase is detected."""


class DocstringGenerator(Protocol):
    """What the docs pipeline needs from a generator.

    The pipeline owns ``remarks``: it assigns the resolved run-wide instruction
    after restoring it from checkpoint metadata, so the attribute is writable.
    """

    remarks: str | None

    async def generate_batch(
        self, items: list[DocstringItem], tone: str
    ) -> tuple[dict[str, str], TokenUsage]:
        """Return ``({id: docstring}, usage)`` for ``items``."""
        ...


class LLMDocstringGenerator:
    """LLM-backed batch generator with banned-phrase silent retry.

    ``remarks`` is a run-wide instruction injected into every prompt. It is held
    here, not in graph state, so a resumed run restores it from checkpoint
    metadata rather than carrying it through the checkpointer.
    """

    def __init__(self, client: LLMClient, remarks: str | None = None) -> None:
        """Initialize the generator with an LLM client and optional instructions.

        Args:
            client: The LLM client to execute generation.
            remarks: Optional supplemental instructions for the model.
        """
        self.chain = client.with_structured_output(BatchDocstringOutput)
        self.remarks = remarks

    async def generate_batch(
        self, items: list[DocstringItem], tone: str
    ) -> tuple[dict[str, str], TokenUsage]:
        """Return ``({id: docstring}, usage)`` for ``items``.

        Performs up to ``BANNED_RETRY_LIMIT`` extra calls covering only the keys
        whose docstring tripped the banned-phrase filter. ``usage`` sums the real
        tokens of every call, retries included.
        """
        result, usage = await self.chain.ainvoke(
            build_batch_docstring_prompt(items, tone, self.remarks)
        )
        accumulated: dict[str, str] = dict(result.docstrings)
        by_key = {item.key: item for item in items}

        for _ in range(BANNED_RETRY_LIMIT):
            offending_keys = [k for k, v in accumulated.items() if contains_banned_phrase(v)]
            if not offending_keys:
                break
            retry_items = [by_key[k] for k in offending_keys if k in by_key]
            if not retry_items:
                break
            retry_result, retry_usage = await self.chain.ainvoke(
                build_batch_docstring_prompt(retry_items, tone, self.remarks)
            )
            usage += retry_usage
            for key, value in retry_result.docstrings.items():
                accumulated[key] = value
        return accumulated, usage
