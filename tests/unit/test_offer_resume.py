"""offer_resume: prompt-or-notice behavior on incomplete-run detection."""

from pathlib import Path

import pytest

from docspatch.commands import docs as docs_cmd
from docspatch.ui import ScriptedPrompter


def stub_no_runs(_root: Path) -> list[str]:
    return []


def stub_one_run(_root: Path) -> list[str]:
    return ["20260520-000000-aaaaaa"]


def test_returns_none_when_no_incomplete_runs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def fake_list(root: Path) -> list[str]:
        return stub_no_runs(root)

    monkeypatch.setattr("docspatch.checkpoints.runs.list_incomplete_runs", fake_list)
    assert docs_cmd.offer_resume(tmp_path, ScriptedPrompter([])) is None


def test_returns_run_id_when_user_confirms(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def fake_list(root: Path) -> list[str]:
        return stub_one_run(root)

    monkeypatch.setattr("docspatch.checkpoints.runs.list_incomplete_runs", fake_list)
    monkeypatch.setattr(docs_cmd, "is_interactive", lambda: True)
    rid = docs_cmd.offer_resume(tmp_path, ScriptedPrompter([True]))
    assert rid == "20260520-000000-aaaaaa"


def test_discards_when_user_declines(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def fake_list(root: Path) -> list[str]:
        return stub_one_run(root)

    discarded = {"called": False}

    async def fake_discard(_root: Path) -> None:
        discarded["called"] = True

    monkeypatch.setattr("docspatch.checkpoints.runs.list_incomplete_runs", fake_list)
    monkeypatch.setattr("docspatch.checkpoints.runs.discard_incomplete_runs", fake_discard)
    monkeypatch.setattr(docs_cmd, "is_interactive", lambda: True)

    assert docs_cmd.offer_resume(tmp_path, ScriptedPrompter([False])) is None
    assert discarded["called"]


def test_headless_returns_none_without_prompting(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def fake_list(root: Path) -> list[str]:
        return stub_one_run(root)

    monkeypatch.setattr("docspatch.checkpoints.runs.list_incomplete_runs", fake_list)
    monkeypatch.setattr(docs_cmd, "is_interactive", lambda: False)
    # Empty ScriptedPrompter would assert if confirm was called.
    assert docs_cmd.offer_resume(tmp_path, ScriptedPrompter([])) is None
