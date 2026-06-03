"""Prompter seam — ScriptedPrompter contract + headless init smoke test."""

import tomllib
from unittest.mock import MagicMock

import pytest

import docspatch.commands.init as init_cmd
from docspatch.pipelines.scout.state import ScanPlan
from docspatch.ui import Prompter, QuestionaryPrompter, ScriptedPrompter


def test_questionary_prompter_satisfies_protocol():
    assert isinstance(QuestionaryPrompter(), Prompter)


def test_scripted_prompter_satisfies_protocol():
    assert isinstance(ScriptedPrompter([]), Prompter)


def test_scripted_prompter_consumes_answers_in_order():
    p = ScriptedPrompter(["a", "b", True, ["x"]])
    assert p.select("q1", ["a", "b"]) == "a"
    assert p.password("q2") == "b"
    assert p.confirm("q3") is True
    assert p.checkbox("q4", {"x": 1}) == ["x"]


def test_scripted_prompter_raises_when_exhausted():
    p = ScriptedPrompter(["only"])
    p.select("first", ["only"])
    with pytest.raises(AssertionError):
        p.select("second", ["only"])


def test_scripted_prompter_dict_choices_select_returns_label_value():
    """Adapter contract: select returns whatever the scripted answer is.
    The caller decides whether choices are labels or values."""
    p = ScriptedPrompter(["balanced"])
    chosen = p.select("Pick tier:", {"⚡ fast": "fast", "⚖ balanced": "balanced"})
    assert chosen == "balanced"


def test_init_runs_end_to_end_with_scripted_prompter(monkeypatch, tmp_path):
    """Headless dp init: no questionary patching, just a scripted answer queue."""
    # Stub out the LLM and cache-scan side effects.
    mock_client = MagicMock()
    mock_client.validate_key.return_value = True
    monkeypatch.setattr("docspatch.pipelines.scout.pipeline.LLMClient", MagicMock(return_value=mock_client))
    monkeypatch.setattr("docspatch.llm.client.validate_api_key", lambda _p, _k: True)
    monkeypatch.setattr(
        "docspatch.pipelines.scout.pipeline.plan_uncached",
        lambda *a, **kw: ScanPlan(uncached=(), cached=(), token_estimate=0),
    )

    answers = ["anthropic", "sk-ant-key", "balanced", "professional", "MIT", False]
    init_cmd.run(
        repo_root=tmp_path,
        global_config_path=tmp_path / "global.toml",
        prompter=ScriptedPrompter(answers),
    )

    data = tomllib.loads((tmp_path / "global.toml").read_text())
    assert data["provider"] == "anthropic"
    assert data["api_key_anthropic"] == "sk-ant-key"
    repo = tomllib.loads((tmp_path / ".docspatch" / "config.toml").read_text())
    assert repo["generator_model"] == "claude-sonnet-4-6"
    assert repo["tone"] == "professional"
    assert (tmp_path / "LICENSE").exists()
