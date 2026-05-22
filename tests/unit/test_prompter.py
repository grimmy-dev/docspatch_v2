"""QuestionaryPrompter never blocks in a non-interactive (CI / piped) session."""

import pytest

from docspatch.ui.prompter import QuestionaryPrompter, is_interactive
from docspatch.utils.errors import ConfigError


@pytest.fixture
def headless(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force a non-interactive context regardless of the real stdin."""
    monkeypatch.setenv("CI", "1")


def test_is_interactive_false_under_ci(headless: None) -> None:
    assert is_interactive() is False


def test_confirm_returns_default_when_headless(headless: None) -> None:
    p = QuestionaryPrompter()
    assert p.confirm("proceed?", default=True) is True
    assert p.confirm("proceed?", default=False) is False


def test_text_returns_default_when_headless(headless: None) -> None:
    assert QuestionaryPrompter().text("name?", default="fallback") == "fallback"


def test_checkbox_returns_empty_when_headless(headless: None) -> None:
    assert QuestionaryPrompter().checkbox("pick:", ["a", "b"]) == []


def test_select_with_default_returns_it_when_headless(headless: None) -> None:
    assert QuestionaryPrompter().select("pick:", ["a", "b"], default="a") == "a"


def test_select_without_default_aborts_when_headless(headless: None) -> None:
    with pytest.raises(ConfigError, match="non-interactive"):
        QuestionaryPrompter().select("pick:", ["a", "b"])


def test_password_aborts_when_headless(headless: None) -> None:
    with pytest.raises(ConfigError, match="non-interactive"):
        QuestionaryPrompter().password("API key?")
