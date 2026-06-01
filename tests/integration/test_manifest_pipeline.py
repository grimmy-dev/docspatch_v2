"""End-to-end: run_docs leaves a manifest with real counts + tokens."""

import asyncio
import json
from pathlib import Path

from docspatch.checkpoints.manifest import manifest_path
from docspatch.llm import TokenUsage
from docspatch.pipelines.docs import run_docs
from docspatch.pipelines.docs.prompts import DocstringItem

FAKE_USAGE = TokenUsage(input_tokens=100, output_tokens=30)


class FakeGenerator:
    remarks: str | None = None

    def __init__(self, docstring: str = "Doc.") -> None:
        self.canned = docstring

    async def generate_batch(self, items: list[DocstringItem], tone: str) -> tuple[dict[str, str], TokenUsage]:
        return {i.key: self.canned for i in items}, FAKE_USAGE


def test_successful_run_persists_manifest_with_counts(tmp_path: Path) -> None:
    src = tmp_path / "m.py"
    src.write_text("def foo():\n    return 1\n")
    run_id = "20260523-000001-aaaaaa"

    asyncio.run(
        run_docs(
            [src],
            FakeGenerator(),
            tone="professional",
            repo_root=tmp_path,
            batch_token_limit=10_000,
            concurrency_limit=1,
            provider="anthropic",
            tier="fast",
            auto_confirm=True,
            run_id=run_id,
        )
    )

    path = manifest_path(tmp_path, run_id)
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["exit_status"] == "success"
    assert data["command"] == "docs"
    assert data["functions_documented"] == 1
    assert data["files_documented"] == ["m.py"]
    assert data["input_tokens"] == FAKE_USAGE.input_tokens
    assert data["output_tokens"] == FAKE_USAGE.output_tokens
    assert data["cost_total"] > 0
    assert data["ended_at"]
    assert data["model"]
