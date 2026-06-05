"""End-to-end docs graph. Behaviour tests with a fake batch generator."""

import asyncio
import contextlib
from pathlib import Path

import pytest

from docspatch.cache import DocsCache, FileDocState
from docspatch.llm import TokenUsage
from docspatch.pipelines.docs import run_docs
from docspatch.pipelines.docs.flags import RunFlags
from docspatch.pipelines.docs.generator import DocstringGenerator
from docspatch.pipelines.docs.prompts import DocstringItem

FAKE_USAGE = TokenUsage(input_tokens=40, output_tokens=12)
"""Canned per-batch token usage every fake generator reports."""


class FakeGenerator:
    """Returns a canned docstring for every requested key. Records every call."""

    remarks: str | None = None

    def __init__(self, docstring: str = "Compute the answer.\n\nReturns:\n    int: The answer.") -> None:
        self.canned = docstring
        self.calls: list[tuple[tuple[str, ...], str]] = []

    async def generate_batch(self, items: list[DocstringItem], tone: str) -> tuple[dict[str, str], TokenUsage]:
        self.calls.append((tuple(i.key for i in items), tone))
        return {i.key: self.canned for i in items}, FAKE_USAGE


def go(
    paths: list[Path],
    generator: DocstringGenerator,
    *,
    tmp_path: Path,
    cache: DocsCache | None = None,
    concurrency_limit: int = 2,
    flags: RunFlags | None = None,
    run_id: str | None = None,
):
    """Run the graph with auto-confirm + sensible defaults."""
    return asyncio.run(
        run_docs(
            paths,
            generator,
            tone="professional",
            repo_root=tmp_path,
            flags=flags,
            batch_token_limit=10_000,
            concurrency_limit=concurrency_limit,
            provider="anthropic",
            tier="fast",
            cache=cache,
            auto_confirm=True,
            run_id=run_id,
        )
    )


class ParseFailingGenerator:
    """Raises ParseFailed on every batch — simulates schema validation exhaustion."""

    remarks: str | None = None

    async def generate_batch(self, items: list[DocstringItem], tone: str) -> tuple[dict[str, str], TokenUsage]:
        from docspatch.utils.errors import ParseFailed

        raise ParseFailed.after_retry(ValueError("schema mismatch"))


def test_parse_failed_batch_is_not_committed(tmp_path: Path) -> None:
    src = tmp_path / "m.py"
    src.write_text("def foo():\n    return 1\n")

    result = go([src], ParseFailingGenerator(), tmp_path=tmp_path)

    # Non-interactive run auto-rejects parse-failed entries — nothing written.
    assert result.functions_documented == 0
    assert result.files_documented == 0


def test_update_regenerates_documented_function(tmp_path: Path) -> None:
    src = tmp_path / "m.py"
    src.write_text('def add(a, b):\n    """Stale."""\n    return a + b\n')

    generator = FakeGenerator("Add two numbers.")
    result = go([src], generator, tmp_path=tmp_path, flags=RunFlags(update=True))

    assert result.functions_documented >= 1
    assert '"""Add two numbers."""' in src.read_text()
    assert "Stale." not in src.read_text()


def test_update_adds_module_docstring(tmp_path: Path) -> None:
    src = tmp_path / "m.py"
    src.write_text("def f():\n    return 1\n")

    go([src], FakeGenerator("Top-level summary."), tmp_path=tmp_path, flags=RunFlags(update=True))

    assert src.read_text().startswith('"""Top-level summary."""')


def test_remarks_reach_the_generator(tmp_path: Path) -> None:
    src = tmp_path / "m.py"
    src.write_text("def f():\n    return 1\n")

    generator = FakeGenerator("doc.")
    go([src], generator, tmp_path=tmp_path, flags=RunFlags(remarks="Use British spelling."))

    assert generator.remarks == "Use British spelling."


def test_fresh_run_has_no_remarks(tmp_path: Path) -> None:
    src = tmp_path / "m.py"
    src.write_text("def f():\n    return 1\n")

    generator = FakeGenerator("doc.")
    go([src], generator, tmp_path=tmp_path)

    assert generator.remarks is None


def test_resume_restores_remarks_from_checkpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import docspatch.pipelines.docs.commit as commit_mod

    src = tmp_path / "m.py"
    src.write_text("def f():\n    return 1\n")
    run_id = "20260522-000000-abcdef"

    def killer(*_args: object, **_kwargs: object) -> str:
        raise KeyboardInterrupt  # hard kill mid-commit — leaves the run resumable

    monkeypatch.setattr(commit_mod, "insert_docstrings", killer)
    with contextlib.suppress(KeyboardInterrupt):
        go(
            [src],
            FakeGenerator("doc."),
            tmp_path=tmp_path,
            flags=RunFlags(remarks="Use British spelling."),
            run_id=run_id,
        )

    monkeypatch.undo()
    healthy = FakeGenerator("doc.")
    go([src], healthy, tmp_path=tmp_path, run_id=run_id)

    assert healthy.calls == []  # generation resumed from checkpoint, no LLM re-call
    assert healthy.remarks == "Use British spelling."


def test_list_incomplete_runs_finds_a_killed_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import docspatch.pipelines.docs.commit as commit_mod
    from docspatch.checkpoints.runs import list_incomplete_runs

    src = tmp_path / "m.py"
    src.write_text("def f():\n    return 1\n")
    run_id = "20260522-120000-abcdef"

    def killer(*_args: object, **_kwargs: object) -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr(commit_mod, "insert_docstrings", killer)
    with contextlib.suppress(KeyboardInterrupt):
        go([src], FakeGenerator("doc."), tmp_path=tmp_path, run_id=run_id)
    monkeypatch.undo()

    assert asyncio.run(list_incomplete_runs(tmp_path)) == [run_id]


def test_summary_panel_reports_real_tokens(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path / "m.py"
    src.write_text("def f():\n    return 1\n")

    go([src], FakeGenerator("doc."), tmp_path=tmp_path)

    out = capsys.readouterr().out
    assert "Docs run complete" in out
    assert "40 / 12" in out  # real per-batch usage from FAKE_USAGE, not an estimate


def test_fully_documented_file_is_noop(tmp_path: Path) -> None:
    src = tmp_path / "sample.py"
    original = '"""Module."""\n\n\ndef add(a: int, b: int) -> int:\n    """Add two numbers."""\n    return a + b\n'
    src.write_text(original)

    generator = FakeGenerator()
    result = go([src], generator, tmp_path=tmp_path)

    assert result.functions_documented == 0
    assert generator.calls == []
    assert src.read_text() == original


def test_preserves_surrounding_code(tmp_path: Path) -> None:
    src = tmp_path / "sample.py"
    src.write_text(
        '"""Module docstring stays put."""\n'
        "\n"
        "from typing import Final\n"
        "\n"
        "# Important constant.\n"
        "ANSWER: Final[int] = 42\n"
        "\n"
        "\n"
        "def add(a: int, b: int) -> int:\n"
        "    return a + b\n"
        "\n"
        "\n"
        "# trailing comment\n"
    )

    go([src], FakeGenerator(docstring="Add a and b."), tmp_path=tmp_path)

    result = src.read_text()
    assert '"""Module docstring stays put."""' in result
    assert "from typing import Final" in result
    assert "# Important constant." in result
    assert "ANSWER: Final[int] = 42" in result
    assert "# trailing comment" in result
    assert "return a + b" in result


def test_writes_cache_entry_after_generation(tmp_path: Path) -> None:
    src = tmp_path / "sample.py"
    src.write_text("def add(a: int, b: int) -> int:\n    return a + b\n")
    cache = DocsCache(tmp_path)

    go([src], FakeGenerator(docstring="Add a and b."), tmp_path=tmp_path, cache=cache)

    state = cache.get("sample.py")
    assert state is not None
    assert "add" in state.functions
    assert state.functions["add"].has_docstring is True


def test_undocumented_function_gains_docstring(tmp_path: Path) -> None:
    src = tmp_path / "sample.py"
    src.write_text("def add(a: int, b: int) -> int:\n    return a + b\n")

    generator = FakeGenerator()
    result = go([src], generator, tmp_path=tmp_path)

    assert result.functions_documented == 1
    new_source = src.read_text()
    assert '"""Compute the answer.' in new_source
    assert "return a + b" in new_source


def test_handles_many_functions_per_file(tmp_path: Path) -> None:
    src = tmp_path / "many.py"
    src.write_text('"""Module."""\n\n\ndef a():\n    return 1\n\n\ndef b():\n    return 2\n\n\ndef c():\n    return 3\n')
    generator = FakeGenerator(docstring="doc.")

    result = go([src], generator, tmp_path=tmp_path)

    assert result.functions_documented == 3
    assert result.files_documented == 1
    text = src.read_text()
    assert text.count('"""doc."""') == 3


def test_one_llm_call_per_batch(tmp_path: Path) -> None:
    """Bundle all 3 fns into a single LLM call (batched generation)."""
    src = tmp_path / "many.py"
    src.write_text('"""Module."""\n\n\ndef a():\n    return 1\n\n\ndef b():\n    return 2\n\n\ndef c():\n    return 3\n')
    gen = FakeGenerator(docstring="d.")

    go([src], gen, tmp_path=tmp_path)

    assert len(gen.calls) == 1
    keys, _tone = gen.calls[0]
    assert sorted(keys) == ["many.py::a", "many.py::b", "many.py::c"]


def test_across_multiple_files(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "a.py").write_text("def x():\n    return 1\n")
    (pkg / "b.py").write_text("def y():\n    return 2\n")

    result = go([pkg / "a.py", pkg / "b.py"], FakeGenerator(docstring="d."), tmp_path=tmp_path)

    assert result.functions_documented == 2
    assert result.files_documented == 2
    assert '"""d."""' in (pkg / "a.py").read_text()
    assert '"""d."""' in (pkg / "b.py").read_text()


def test_respects_concurrency_limit(tmp_path: Path) -> None:
    """Concurrency cap applies across batches (semaphore around each LLM call)."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    for i in range(6):
        (pkg / f"m{i}.py").write_text(f"def f{i}():\n    return {i}\n")

    class TrackingGenerator:
        remarks: str | None = None

        def __init__(self) -> None:
            self.in_flight = 0
            self.peak = 0

        async def generate_batch(self, items: list[DocstringItem], tone: str) -> tuple[dict[str, str], TokenUsage]:
            self.in_flight += 1
            self.peak = max(self.peak, self.in_flight)
            await asyncio.sleep(0.02)
            self.in_flight -= 1
            return {i.key: "d." for i in items}, FAKE_USAGE

    gen = TrackingGenerator()
    paths = [pkg / f"m{i}.py" for i in range(6)]
    asyncio.run(
        run_docs(
            paths,
            gen,
            tone="professional",
            repo_root=tmp_path,
            batch_token_limit=1,  # force one batch per fn
            concurrency_limit=2,
            provider="anthropic",
            tier="fast",
            auto_confirm=True,
        )
    )

    assert gen.peak <= 2


def test_skips_cache_hits(tmp_path: Path) -> None:
    src = tmp_path / "s.py"
    src.write_text("def a():\n    return 1\n")
    cache = DocsCache(tmp_path)

    go([src], FakeGenerator(docstring="d."), tmp_path=tmp_path, cache=cache)

    gen2 = FakeGenerator()
    result = go([src], gen2, tmp_path=tmp_path, cache=cache)

    assert gen2.calls == []
    assert result.functions_documented == 0


def test_writes_each_file_once(tmp_path: Path) -> None:
    """Per-file single libcst pass: each fn inserted in one atomic write."""
    src = tmp_path / "two.py"
    src.write_text('"""Module."""\n\n\ndef a():\n    return 1\n\n\ndef b():\n    return 2\n')

    go([src], FakeGenerator(docstring="d."), tmp_path=tmp_path)

    final = src.read_text()
    assert final.count('"""d."""') == 2
    assert "return 1" in final
    assert "return 2" in final


def test_decline_confirm_writes_nothing(tmp_path: Path) -> None:
    """Cancelling at the confirm gate exits clean — no partial writes."""
    src = tmp_path / "x.py"
    original = "def a():\n    return 1\n"
    src.write_text(original)

    from docspatch.ui import ScriptedPrompter

    declined = ScriptedPrompter([False])
    result = asyncio.run(
        run_docs(
            [src],
            FakeGenerator(),
            tone="professional",
            repo_root=tmp_path,
            batch_token_limit=10_000,
            concurrency_limit=2,
            provider="anthropic",
            tier="fast",
            prompter=declined,
        )
    )

    assert result.confirmed is False
    assert src.read_text() == original


def test_successful_run_clears_checkpoint_thread(tmp_path: Path) -> None:
    """Thread is removed from sqlite saver after successful commit."""
    src = tmp_path / "a.py"
    src.write_text("def x():\n    return 1\n")

    go([src], FakeGenerator(docstring="d."), tmp_path=tmp_path)

    db_path = tmp_path / ".docspatch" / "checkpoints" / "docs.sqlite"
    if db_path.exists():
        import sqlite3

        with sqlite3.connect(db_path) as conn:
            rows = conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()
            assert rows[0] == 0


def test_partial_generation_persists_completed_batches(tmp_path: Path) -> None:
    """Crash mid-generation leaves the first batch's state in the sqlite checkpoint."""
    import pytest

    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "a.py").write_text('"""Module."""\n\n\ndef x():\n    return 1\n')
    (pkg / "b.py").write_text('"""Module."""\n\n\ndef y():\n    return 2\n')

    class Halfway:
        remarks: str | None = None

        def __init__(self) -> None:
            self.calls = 0

        async def generate_batch(self, items: list[DocstringItem], tone: str) -> tuple[dict[str, str], TokenUsage]:
            self.calls += 1
            if self.calls == 1:
                return {i.key: "d." for i in items}, FAKE_USAGE
            raise RuntimeError("crash")

    with pytest.raises(RuntimeError, match="crash"):
        asyncio.run(
            run_docs(
                [pkg / "a.py", pkg / "b.py"],
                Halfway(),
                tone="professional",
                repo_root=tmp_path,
                batch_token_limit=1,
                concurrency_limit=1,
                provider="anthropic",
                tier="fast",
                auto_confirm=True,
            )
        )

    db_path = tmp_path / ".docspatch" / "checkpoints" / "docs.sqlite"
    assert db_path.exists()


def test_resume_skips_completed_batches(tmp_path: Path) -> None:
    """Re-running with the same run_id skips batches already persisted in the checkpoint."""
    from docspatch.utils.errors import TransientExhausted

    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "a.py").write_text('"""Module."""\n\n\ndef x():\n    return 1\n')
    (pkg / "b.py").write_text('"""Module."""\n\n\ndef y():\n    return 2\n')

    class Halfway:
        remarks: str | None = None

        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        async def generate_batch(self, items: list[DocstringItem], tone: str) -> tuple[dict[str, str], TokenUsage]:
            self.calls.append([i.key for i in items])
            if len(self.calls) == 1:
                return {i.key: "first." for i in items}, FAKE_USAGE
            raise TransientExhausted.after(3, RuntimeError("rate_limit"))

    run_id = "20260519-000000-abcdef"

    async def decline(_g: DocstringGenerator) -> None:
        return None

    asyncio.run(
        run_docs(
            [pkg / "a.py", pkg / "b.py"],
            Halfway(),
            tone="professional",
            repo_root=tmp_path,
            batch_token_limit=1,
            concurrency_limit=1,
            provider="anthropic",
            tier="fast",
            auto_confirm=True,
            run_id=run_id,
            switch_handler=decline,
        )
    )

    healthy = FakeGenerator(docstring="second.")
    asyncio.run(
        run_docs(
            [pkg / "a.py", pkg / "b.py"],
            healthy,
            tone="professional",
            repo_root=tmp_path,
            batch_token_limit=1,
            concurrency_limit=1,
            provider="anthropic",
            tier="fast",
            auto_confirm=True,
            run_id=run_id,
        )
    )

    # One file committed per run; combined output has both runs' docstrings.
    text_a = (pkg / "a.py").read_text()
    text_b = (pkg / "b.py").read_text()
    combined = text_a + text_b
    assert '"""first."""' in combined
    assert '"""second."""' in combined

    # Healthy generator must only be invoked for the batch missed by the first run.
    assert len(healthy.calls) == 1


def test_switch_handler_resumes_after_transient_exhausted(tmp_path: Path) -> None:
    """Exhausted batch triggers switch_handler; new generator resumes pending batches."""
    from docspatch.utils.errors import TransientExhausted

    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "a.py").write_text("def x():\n    return 1\n")
    (pkg / "b.py").write_text("def y():\n    return 2\n")

    class Exhausted:
        remarks: str | None = None

        async def generate_batch(self, items: list[DocstringItem], tone: str) -> tuple[dict[str, str], TokenUsage]:
            raise TransientExhausted.after(3, RuntimeError("rate_limit"))

    good = FakeGenerator(docstring="after.")

    async def handler(_current: DocstringGenerator) -> DocstringGenerator:
        return good

    result = asyncio.run(
        run_docs(
            [pkg / "a.py", pkg / "b.py"],
            Exhausted(),
            tone="professional",
            repo_root=tmp_path,
            batch_token_limit=1,
            concurrency_limit=2,
            provider="anthropic",
            tier="fast",
            auto_confirm=True,
            switch_handler=handler,
        )
    )

    assert result.functions_documented == 2
    assert '"""after."""' in (pkg / "a.py").read_text()
    assert '"""after."""' in (pkg / "b.py").read_text()


def test_switch_handler_decline_returns_partial(tmp_path: Path) -> None:
    """Handler returning None aborts; completed batches retained."""
    from docspatch.utils.errors import TransientExhausted

    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "a.py").write_text("def x():\n    return 1\n")

    class Exhausted:
        remarks: str | None = None

        async def generate_batch(self, items: list[DocstringItem], tone: str) -> tuple[dict[str, str], TokenUsage]:
            raise TransientExhausted.after(3, RuntimeError("429"))

    async def handler(_current: DocstringGenerator) -> None:
        return None

    result = asyncio.run(
        run_docs(
            [pkg / "a.py"],
            Exhausted(),
            tone="professional",
            repo_root=tmp_path,
            batch_token_limit=1,
            concurrency_limit=1,
            provider="anthropic",
            tier="fast",
            auto_confirm=True,
            switch_handler=handler,
        )
    )
    assert result.functions_documented == 0
    assert (pkg / "a.py").read_text() == "def x():\n    return 1\n"


def test_completed_batches_not_reissued_after_switch(tmp_path: Path) -> None:
    """New generator after switch only sees pending (failed/cancelled) batches."""
    from docspatch.utils.errors import TransientExhausted

    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "a.py").write_text('"""Module."""\n\n\ndef x():\n    return 1\n')
    (pkg / "b.py").write_text('"""Module."""\n\n\ndef y():\n    return 2\n')
    (pkg / "c.py").write_text('"""Module."""\n\n\ndef z():\n    return 3\n')

    class FirstOkRestExhausted:
        remarks: str | None = None

        def __init__(self) -> None:
            self.calls = 0

        async def generate_batch(self, items: list[DocstringItem], tone: str) -> tuple[dict[str, str], TokenUsage]:
            self.calls += 1
            if self.calls == 1:
                return {i.key: "ok." for i in items}, FAKE_USAGE
            raise TransientExhausted.after(3, RuntimeError("rate_limit"))

    good = FakeGenerator(docstring="new.")

    async def handler(_current: DocstringGenerator) -> DocstringGenerator:
        return good

    asyncio.run(
        run_docs(
            [pkg / "a.py", pkg / "b.py", pkg / "c.py"],
            FirstOkRestExhausted(),
            tone="professional",
            repo_root=tmp_path,
            batch_token_limit=1,
            concurrency_limit=1,
            provider="anthropic",
            tier="fast",
            auto_confirm=True,
            switch_handler=handler,
        )
    )

    seen_keys = [k for call_keys, _ in good.calls for k in call_keys]
    assert "pkg/a.py::x" not in seen_keys
    assert sorted(seen_keys) == ["pkg/b.py::y", "pkg/c.py::z"]


def _ids(payload: dict) -> list[str]:
    """Every entry id in an interrupt payload."""
    return [f"{e['rel']}::{e['qualname']}" for e in payload["entries"]]


def _choice(*, accepted=(), rejected=(), rerun=(), feedback=None, aborted=False) -> dict:
    """Build a review choice dict, the shape ``review_handler`` must return."""
    return {
        "accepted": list(accepted),
        "rejected": list(rejected),
        "rerun": list(rerun),
        "feedback": dict(feedback or {}),
        "aborted": aborted,
    }


def test_reviewer_reject_skips_that_function_only(tmp_path: Path) -> None:
    """Rejecting one entry writes the others but not the rejected one."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "a.py").write_text('"""Module."""\n\n\ndef x():\n    return 1\n')
    (pkg / "b.py").write_text('"""Module."""\n\n\ndef y():\n    return 2\n')

    def handler(payload: dict) -> dict:
        ids = _ids(payload)
        return _choice(accepted=ids[:1], rejected=ids[1:])

    result = asyncio.run(
        run_docs(
            [pkg / "a.py", pkg / "b.py"],
            FakeGenerator(docstring="d."),
            tone="professional",
            repo_root=tmp_path,
            batch_token_limit=1,
            concurrency_limit=1,
            provider="anthropic",
            tier="fast",
            auto_confirm=True,
            review_handler=handler,
        )
    )

    assert result.functions_documented == 1
    assert result.files_documented == 1
    text_a = (pkg / "a.py").read_text()
    text_b = (pkg / "b.py").read_text()
    written = ('"""d."""' in text_a) + ('"""d."""' in text_b)
    assert written == 1


def test_reviewer_abort_writes_nothing(tmp_path: Path) -> None:
    """Aborting at review clears the checkpoint and writes no files."""
    src = tmp_path / "m.py"
    original = "def x():\n    return 1\n"
    src.write_text(original)

    result = asyncio.run(
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
            review_handler=lambda _p: _choice(aborted=True),
        )
    )

    assert result.aborted is True
    assert src.read_text() == original


def test_reviewer_accept_all_writes_everything(tmp_path: Path) -> None:
    src = tmp_path / "m.py"
    src.write_text('"""Module."""\n\n\ndef x():\n    return 1\n\n\ndef y():\n    return 2\n')

    result = asyncio.run(
        run_docs(
            [src],
            FakeGenerator(docstring="d."),
            tone="professional",
            repo_root=tmp_path,
            batch_token_limit=10_000,
            concurrency_limit=1,
            provider="anthropic",
            tier="fast",
            auto_confirm=True,
            review_handler=lambda p: _choice(accepted=_ids(p)),
        )
    )

    assert result.functions_documented == 2
    assert src.read_text().count('"""d."""') == 2


def test_review_abort_clears_checkpoint_threads(tmp_path: Path) -> None:
    """Abort removes both the docs and review checkpoint threads."""
    src = tmp_path / "m.py"
    src.write_text("def x():\n    return 1\n")

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
            review_handler=lambda _p: _choice(aborted=True),
        )
    )

    db_path = tmp_path / ".docspatch" / "checkpoints" / "docs.sqlite"
    if db_path.exists():
        import sqlite3

        with sqlite3.connect(db_path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0] == 0


def test_cancelled_mid_wave_invokes_switch_handler(tmp_path: Path) -> None:
    """CancelledError during generation (Ctrl+C) opens the switch menu, not abort."""
    src = tmp_path / "a.py"
    src.write_text("def x():\n    return 1\n")

    class Cancelling:
        remarks: str | None = None

        async def generate_batch(self, items: list[DocstringItem], tone: str) -> tuple[dict[str, str], TokenUsage]:
            raise asyncio.CancelledError

    good = FakeGenerator(docstring="resumed.")

    async def handler(_current: DocstringGenerator) -> DocstringGenerator:
        return good

    result = asyncio.run(
        run_docs(
            [src],
            Cancelling(),
            tone="professional",
            repo_root=tmp_path,
            batch_token_limit=1,
            concurrency_limit=1,
            provider="anthropic",
            tier="fast",
            auto_confirm=True,
            switch_handler=handler,
        )
    )
    assert result.functions_documented == 1
    assert '"""resumed."""' in src.read_text()


class TrackingGen:
    """Returns canned docstring v1 then v2; records every batch invocation."""

    remarks: str | None = None

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[list[DocstringItem]] = []

    async def generate_batch(self, items: list[DocstringItem], tone: str) -> tuple[dict[str, str], TokenUsage]:
        self.calls.append(list(items))
        doc = self.responses.pop(0) if self.responses else "fallback."
        return {i.key: doc for i in items}, FAKE_USAGE


def test_rerun_regenerates_with_feedback_then_accepts(tmp_path: Path) -> None:
    """Review queues fn for rerun → generator re-invoked with feedback → second review accepts."""
    src = tmp_path / "m.py"
    src.write_text('"""Module."""\n\n\ndef f():\n    return 1\n')

    gen = TrackingGen(responses=["initial.", "improved."])
    seen: list[bool] = []

    def handler(payload: dict) -> dict:
        seen.append(payload["allow_rerun"])
        ids = _ids(payload)
        if len(seen) == 1:
            return _choice(rerun=ids, feedback={"m.py::f": "more detail please"})
        return _choice(accepted=ids)

    result = asyncio.run(
        run_docs(
            [src],
            gen,
            tone="professional",
            repo_root=tmp_path,
            batch_token_limit=10_000,
            concurrency_limit=1,
            provider="anthropic",
            tier="fast",
            auto_confirm=True,
            review_handler=handler,
        )
    )

    assert result.functions_documented == 1
    assert '"""improved."""' in src.read_text()
    assert len(gen.calls) == 2
    assert gen.calls[1][0].feedback == ("more detail please",)


def test_rerun_round_cap_disables_rerun_on_sixth_review(tmp_path: Path) -> None:
    """After 5 rerun rounds, the 6th review payload must carry allow_rerun=False."""
    src = tmp_path / "m.py"
    src.write_text("def f():\n    return 1\n")

    gen = TrackingGen(responses=[f"v{i}." for i in range(10)])
    seen_allow_rerun: list[bool] = []

    def handler(payload: dict) -> dict:
        seen_allow_rerun.append(payload["allow_rerun"])
        ids = _ids(payload)
        if payload["allow_rerun"]:
            return _choice(rerun=ids, feedback={"m.py::f": f"round {len(seen_allow_rerun)}"})
        return _choice(accepted=ids)

    asyncio.run(
        run_docs(
            [src],
            gen,
            tone="professional",
            repo_root=tmp_path,
            batch_token_limit=10_000,
            concurrency_limit=1,
            provider="anthropic",
            tier="fast",
            auto_confirm=True,
            review_handler=handler,
        )
    )

    assert seen_allow_rerun[:5] == [True] * 5
    assert seen_allow_rerun[5] is False


def test_rerun_keeps_accepted_and_regenerates_only_rerun(tmp_path: Path) -> None:
    """Accepted entries from round 1 survive to final commit; rerun entries regenerate."""
    src = tmp_path / "m.py"
    src.write_text("def a():\n    return 1\n\n\ndef b():\n    return 2\n")

    class KeyedGen:
        remarks: str | None = None

        def __init__(self) -> None:
            self.call = 0

        async def generate_batch(self, items: list[DocstringItem], tone: str) -> tuple[dict[str, str], TokenUsage]:
            self.call += 1
            out: dict[str, str] = {}
            for it in items:
                qn = it.key.split("::")[-1]
                if qn == "a" and self.call > 1:
                    out[it.key] = "doc-a-v2."
                else:
                    out[it.key] = f"doc-{qn}."
            return out, FAKE_USAGE

    gen = KeyedGen()
    round_n = [0]

    def handler(payload: dict) -> dict:
        round_n[0] += 1
        entries = payload["entries"]
        if round_n[0] == 1:
            accepted = [f"{e['rel']}::{e['qualname']}" for e in entries if e["qualname"] == "b"]
            rerun = [f"{e['rel']}::{e['qualname']}" for e in entries if e["qualname"] == "a"]
            return _choice(accepted=accepted, rerun=rerun, feedback={"m.py::a": "more detail"})
        return _choice(accepted=_ids(payload))

    result = asyncio.run(
        run_docs(
            [src],
            gen,
            tone="professional",
            repo_root=tmp_path,
            batch_token_limit=10_000,
            concurrency_limit=1,
            provider="anthropic",
            tier="fast",
            auto_confirm=True,
            review_handler=handler,
        )
    )

    assert result.functions_documented == 2
    final = src.read_text()
    assert '"""doc-a-v2."""' in final
    assert '"""doc-b."""' in final


def test_rerun_feedback_accumulates_across_rounds(tmp_path: Path) -> None:
    """Second rerun's prompt receives both feedback strings (oldest first)."""
    src = tmp_path / "m.py"
    src.write_text('"""Module."""\n\n\ndef f():\n    return 1\n')

    gen = TrackingGen(responses=["v1.", "v2.", "v3."])
    round_n = [0]

    def handler(payload: dict) -> dict:
        round_n[0] += 1
        ids = _ids(payload)
        if round_n[0] == 1:
            return _choice(rerun=ids, feedback={"m.py::f": "first note"})
        if round_n[0] == 2:
            return _choice(rerun=ids, feedback={"m.py::f": "second note"})
        return _choice(accepted=ids)

    asyncio.run(
        run_docs(
            [src],
            gen,
            tone="professional",
            repo_root=tmp_path,
            batch_token_limit=10_000,
            concurrency_limit=1,
            provider="anthropic",
            tier="fast",
            auto_confirm=True,
            review_handler=handler,
        )
    )

    assert len(gen.calls) == 3
    assert gen.calls[2][0].feedback == ("first note", "second note")


# --- commit node ----------------------------------------------------------


def _two_file_pkg(tmp_path: Path) -> Path:
    """A package with two undocumented files."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "a.py").write_text("def x():\n    return 1\n")
    (pkg / "b.py").write_text("def y():\n    return 2\n")
    return pkg


def test_commit_cleans_journal_and_snapshots_on_success(tmp_path: Path) -> None:
    """A clean commit leaves no journal or snapshot directory behind."""
    src = tmp_path / "m.py"
    src.write_text("def x():\n    return 1\n")

    go([src], FakeGenerator(docstring="d."), tmp_path=tmp_path)

    checkpoints = tmp_path / ".docspatch" / "checkpoints"
    assert not list(checkpoints.glob("commit-*.journal"))
    assert not list(checkpoints.glob("originals-*"))
    assert '"""d."""' in src.read_text()


def test_commit_hash_mismatch_skip_leaves_file_untouched(tmp_path: Path) -> None:
    """A file edited since planning, answered 'skip', is not written."""
    src = tmp_path / "m.py"
    original = "def x():\n    return 1\n"
    src.write_text(original)
    cache = DocsCache(tmp_path)
    cache.set("m.py", FileDocState(path="m.py", file_hash="STALE", functions={}))

    def handler(payload: dict) -> dict:
        if payload["type"] == "hash_mismatch":
            return {"action": "skip"}
        return _choice(accepted=_ids(payload))

    result = asyncio.run(
        run_docs(
            [src],
            FakeGenerator(docstring="d."),
            tone="professional",
            repo_root=tmp_path,
            batch_token_limit=10_000,
            concurrency_limit=1,
            provider="anthropic",
            tier="fast",
            cache=cache,
            auto_confirm=True,
            review_handler=handler,
        )
    )

    assert result.functions_documented == 0
    assert result.skipped_files == 1
    assert src.read_text() == original


def test_commit_hash_mismatch_force_writes_file(tmp_path: Path) -> None:
    """Answering 'force' overwrites the concurrently-edited file."""
    src = tmp_path / "m.py"
    src.write_text("def x():\n    return 1\n")
    cache = DocsCache(tmp_path)
    cache.set("m.py", FileDocState(path="m.py", file_hash="STALE", functions={}))

    def handler(payload: dict) -> dict:
        if payload["type"] == "hash_mismatch":
            return {"action": "force"}
        return _choice(accepted=_ids(payload))

    result = asyncio.run(
        run_docs(
            [src],
            FakeGenerator(docstring="d."),
            tone="professional",
            repo_root=tmp_path,
            batch_token_limit=10_000,
            concurrency_limit=1,
            provider="anthropic",
            tier="fast",
            cache=cache,
            auto_confirm=True,
            review_handler=handler,
        )
    )

    assert result.functions_documented == 1
    assert '"""d."""' in src.read_text()


def test_commit_hash_mismatch_abort_reports_error(tmp_path: Path) -> None:
    """Answering 'abort' stops the commit and reports an error."""
    src = tmp_path / "m.py"
    original = "def x():\n    return 1\n"
    src.write_text(original)
    cache = DocsCache(tmp_path)
    cache.set("m.py", FileDocState(path="m.py", file_hash="STALE", functions={}))

    def handler(payload: dict) -> dict:
        if payload["type"] == "hash_mismatch":
            return {"action": "abort"}
        return _choice(accepted=_ids(payload))

    result = asyncio.run(
        run_docs(
            [src],
            FakeGenerator(docstring="d."),
            tone="professional",
            repo_root=tmp_path,
            batch_token_limit=10_000,
            concurrency_limit=1,
            provider="anthropic",
            tier="fast",
            cache=cache,
            auto_confirm=True,
            review_handler=handler,
        )
    )

    assert result.error is not None
    assert result.functions_documented == 0
    assert src.read_text() == original


def test_commit_rolls_back_committed_files_on_write_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A libcst failure on file N restores files 1..N-1 from their snapshots."""
    import docspatch.pipelines.docs.commit as commit_mod

    pkg = _two_file_pkg(tmp_path)
    original_a = (pkg / "a.py").read_text()
    real_insert = commit_mod.insert_docstrings
    calls = [0]

    def flaky(source: str, *, items: list) -> str:
        calls[0] += 1
        if calls[0] == 2:
            raise RuntimeError("libcst boom")
        return real_insert(source, items=items)

    monkeypatch.setattr(commit_mod, "insert_docstrings", flaky)

    result = go([pkg / "a.py", pkg / "b.py"], FakeGenerator(docstring="d."), tmp_path=tmp_path)

    assert result.error is not None
    assert result.functions_documented == 0
    assert (pkg / "a.py").read_text() == original_a  # rolled back
    checkpoints = tmp_path / ".docspatch" / "checkpoints"
    assert not list(checkpoints.glob("commit-*.journal"))
    assert not list(checkpoints.glob("originals-*"))


def test_commit_resumes_at_next_uncommitted_file_after_kill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A hard kill mid-commit leaves a journal; the rerun finishes the rest, no LLM re-call."""
    import docspatch.pipelines.docs.commit as commit_mod

    pkg = _two_file_pkg(tmp_path)
    real_insert = commit_mod.insert_docstrings
    calls = [0]

    def killer(source: str, *, items: list) -> str:
        calls[0] += 1
        if calls[0] == 2:
            raise KeyboardInterrupt  # uncaught — simulates a hard kill mid-commit
        return real_insert(source, items=items)

    monkeypatch.setattr(commit_mod, "insert_docstrings", killer)
    run_id = "20260521-000000-aaaaaa"

    def invoke(generator: DocstringGenerator) -> object:
        return asyncio.run(
            run_docs(
                [pkg / "a.py", pkg / "b.py"],
                generator,
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

    with contextlib.suppress(KeyboardInterrupt):
        invoke(FakeGenerator(docstring="d."))

    monkeypatch.setattr(commit_mod, "insert_docstrings", real_insert)
    healthy = FakeGenerator(docstring="d.")
    invoke(healthy)

    assert healthy.calls == []  # generation resumed from checkpoint, no LLM re-call
    assert '"""d."""' in (pkg / "a.py").read_text()
    assert '"""d."""' in (pkg / "b.py").read_text()


def test_commit_skips_unparseable_file(tmp_path: Path) -> None:
    """A file that stops parsing before commit is skipped; the rest still commit."""
    pkg = _two_file_pkg(tmp_path)

    def handler(payload: dict) -> dict:
        if payload["type"] == "review":
            (pkg / "b.py").write_text("def (((\n")  # corrupt b before commit
            return _choice(accepted=_ids(payload))
        return {"action": "skip"}

    result = asyncio.run(
        run_docs(
            [pkg / "a.py", pkg / "b.py"],
            FakeGenerator(docstring="d."),
            tone="professional",
            repo_root=tmp_path,
            batch_token_limit=10_000,
            concurrency_limit=1,
            provider="anthropic",
            tier="fast",
            auto_confirm=True,
            review_handler=handler,
        )
    )

    assert result.functions_documented == 1
    assert result.skipped_files == 1
    assert '"""d."""' in (pkg / "a.py").read_text()


# --- per-call timeout -------------------------------------------------------


def test_hanging_call_times_out_and_switch_recovers(tmp_path: Path) -> None:
    """A hung LLM call is cancelled at call_timeout; the switched generator finishes the batch."""
    src = tmp_path / "m.py"
    src.write_text("def x():\n    return 1\n")

    class HangingGenerator:
        remarks: str | None = None

        async def generate_batch(self, items: list[DocstringItem], tone: str) -> tuple[dict[str, str], TokenUsage]:
            await asyncio.sleep(30)  # never returns within call_timeout
            return {}, FAKE_USAGE

    healthy = FakeGenerator(docstring="recovered.")

    async def handler(_current: DocstringGenerator) -> DocstringGenerator:
        return healthy

    result = asyncio.run(
        run_docs(
            [src],
            HangingGenerator(),
            tone="professional",
            repo_root=tmp_path,
            batch_token_limit=10_000,
            concurrency_limit=1,
            provider="anthropic",
            tier="fast",
            call_timeout=0.1,
            auto_confirm=True,
            switch_handler=handler,
        )
    )

    assert result.functions_documented == 1
    assert '"""recovered."""' in src.read_text()


def test_hanging_call_without_switch_raises(tmp_path: Path) -> None:
    """A hung call with no switch handler exhausts the run rather than blocking forever."""
    from docspatch.utils.errors import TransientExhausted

    src = tmp_path / "m.py"
    src.write_text("def x():\n    return 1\n")

    class HangingGenerator:
        remarks: str | None = None

        async def generate_batch(self, items: list[DocstringItem], tone: str) -> tuple[dict[str, str], TokenUsage]:
            await asyncio.sleep(30)
            return {}, FAKE_USAGE

    with pytest.raises(TransientExhausted):
        asyncio.run(
            run_docs(
                [src],
                HangingGenerator(),
                tone="professional",
                repo_root=tmp_path,
                batch_token_limit=10_000,
                concurrency_limit=1,
                provider="anthropic",
                tier="fast",
                call_timeout=0.1,
                auto_confirm=True,
            )
        )


def test_completed_run_rerun_is_zero_llm_calls(tmp_path: Path) -> None:
    """Cache populated by a clean run → next run on the same files makes no LLM calls."""
    src = tmp_path / "m.py"
    src.write_text("def foo():\n    return 1\n")

    cache = DocsCache(tmp_path)
    first = FakeGenerator("done.")
    go([src], first, tmp_path=tmp_path, cache=cache)
    assert first.calls, "first run should have generated"

    second = FakeGenerator("done.")
    go([src], second, tmp_path=tmp_path, cache=cache)
    assert second.calls == []


def test_resume_twice_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Killing once, then resuming twice with the same run_id produces one finished file."""
    import docspatch.pipelines.docs.commit as commit_mod

    src = tmp_path / "m.py"
    src.write_text("def f():\n    return 1\n")
    run_id = "20260523-000000-feedbe"

    real = commit_mod.insert_docstrings
    calls = [0]

    def once_kill(source: str, *, items: list) -> str:
        calls[0] += 1
        if calls[0] == 1:
            raise KeyboardInterrupt
        return real(source, items=items)

    monkeypatch.setattr(commit_mod, "insert_docstrings", once_kill)
    with contextlib.suppress(KeyboardInterrupt):
        go([src], FakeGenerator("d."), tmp_path=tmp_path, run_id=run_id)

    monkeypatch.setattr(commit_mod, "insert_docstrings", real)
    a = FakeGenerator("d.")
    go([src], a, tmp_path=tmp_path, run_id=run_id)
    after_first_resume = src.read_text()

    b = FakeGenerator("d.")
    go([src], b, tmp_path=tmp_path, run_id=run_id)

    assert a.calls == []  # resume reused checkpoint
    assert b.calls == []  # second resume found no incomplete run; cache covered everything
    assert src.read_text() == after_first_resume
