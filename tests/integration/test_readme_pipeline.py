"""README pipeline: freshness gate and manifest commit-on-accept lifecycle."""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

from docspatch.llm import TokenUsage
from docspatch.manifest import ChangeManifest
from docspatch.pipelines.readme.pipeline import generate_readme, scope_state
from docspatch.ui import ScriptedPrompter


class FakeGen:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, **kwargs) -> tuple[str, TokenUsage]:  # noqa: ANN003
        self.calls += 1
        return "# demo\n\nbody", TokenUsage(1, 1)


def _run(tmp_path: Path, out: Path, generator, answers: list) -> object:
    return asyncio.run(
        generate_readme(
            tmp_path,
            ".",
            out,
            analysis_client=MagicMock(),
            generator=generator,
            prompter=ScriptedPrompter(answers),
            remarks=None,
            provider="anthropic",
            tier="balanced",
        )
    )


def test_freshness_gate_skips_generation_with_zero_calls(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    out = tmp_path / "README.md"
    out.write_text("# demo\n")
    ChangeManifest(tmp_path).commit("readme", scope_state(tmp_path, ".").hashes)

    gen = FakeGen()
    result = _run(tmp_path, out, gen, [])
    assert result.written is False
    assert result.usage == TokenUsage()
    assert gen.calls == 0  # no LLM, generator never touched


def test_manifest_commit_on_accept(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    out = tmp_path / "README.md"

    async def fake_ainvoke(_state):  # noqa: ANN202
        return {"woven": "CTX", "usage": TokenUsage()}

    monkeypatch.setattr("docspatch.pipelines.readme.graph.build_readme_graph", lambda *a, **k: MagicMock(ainvoke=fake_ainvoke))

    result = _run(tmp_path, out, FakeGen(), ["accept"])
    assert result.written
    assert out.read_text().startswith("# demo")
    assert ChangeManifest(tmp_path).baseline("readme") is not None


def test_discarded_run_leaves_baseline_untouched(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    out = tmp_path / "README.md"

    async def fake_ainvoke(_state):  # noqa: ANN202
        return {"woven": "CTX", "usage": TokenUsage()}

    monkeypatch.setattr("docspatch.pipelines.readme.graph.build_readme_graph", lambda *a, **k: MagicMock(ainvoke=fake_ainvoke))

    result = _run(tmp_path, out, FakeGen(), ["cancel"])
    assert result.written is False
    assert not out.exists()
    assert ChangeManifest(tmp_path).baseline("readme") is None  # next run re-detects
