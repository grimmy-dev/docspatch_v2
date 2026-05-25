"""Prompter seam — single boundary between commands and the interactive layer.

Two adapters ship with the package:

- `QuestionaryPrompter`: the real terminal UI (default everywhere).
- `ScriptedPrompter`: consumes a pre-recorded queue of answers. Used by tests
  and the future `--yes` / headless mode so commands never need to monkeypatch
  the global `questionary` module.

Choices accept either a plain `list[str]` (label == value) or a `dict[label, value]`
so commands can present friendly labels while returning typed values.
"""

import asyncio
import os
import sys
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Protocol, cast, runtime_checkable

import questionary

from docspatch.utils.errors import ConfigError

Choices = list[str] | Mapping[str, object]


def is_interactive() -> bool:
    """True when prompting is safe — stdin is a TTY and no CI signal is set."""
    return sys.stdin.isatty() and not os.environ.get("CI")


@runtime_checkable
class Prompter(Protocol):
    """Interactive question API. Implementations must return concrete values, not chains."""

    def select(self, question: str, choices: Choices, default: str | None = None) -> object:
        """Pick one option. Returns the selected value (dict-style choices return the mapped value)."""
        ...

    def password(self, question: str) -> str:
        """Read a secret without echo. Raises on headless sessions — no safe fallback."""
        ...

    def confirm(self, question: str, default: bool = True) -> bool:
        """Yes/no prompt. Returns ``default`` when headless."""
        ...

    def checkbox(self, question: str, choices: Choices) -> list[object]:
        """Pick zero or more options. Returns the selected values in choice order."""
        ...

    def text(self, question: str, default: str = "") -> str:
        """Free-form string. Returns ``default`` when headless or when input is empty."""
        ...


class QuestionaryPrompter:
    """Real terminal prompter. Returns the selected `value` for dict-style choices.

    In a non-interactive session (piped/CI) questionary would hang forever, so
    each call falls back to its default answer — or aborts when none is safe.
    """

    def select(self, question: str, choices: Choices, default: str | None = None) -> object:
        """Ask the user to choose one option from a list."""
        if not is_interactive():
            if default is None:
                raise ConfigError.headless_no_input(question)
            return default
        return questionary.select(question, choices=_to_questionary_choices(choices), default=default).ask()

    def password(self, question: str) -> str:
        """Ask the user to securely input a password string."""
        if not is_interactive():
            raise ConfigError.headless_no_input(question)
        return str(questionary.password(question).ask())

    def confirm(self, question: str, default: bool = True) -> bool:
        """Ask the user for a yes-no confirmation."""
        if not is_interactive():
            return default
        result = questionary.confirm(question, default=default).ask()
        return bool(result)

    def checkbox(self, question: str, choices: Choices) -> list[object]:
        """Ask the user to select multiple items from a list."""
        if not is_interactive():
            return []
        return questionary.checkbox(question, choices=_to_questionary_choices(choices)).ask() or []

    def text(self, question: str, default: str = "") -> str:
        """Ask the user to provide a text string input."""
        if not is_interactive():
            return default
        result = questionary.text(question, default=default).ask()
        return "" if result is None else str(result)


class ScriptedPrompter:
    """Replays answers in order. One answer consumed per call; raises if exhausted."""

    def __init__(self, answers: Iterable[object]) -> None:
        """Initialize the prompter with a predefined list of answers.

        Args:
            answers: An iterable of return values for successive prompts.
        """
        self._answers = list(answers)
        self._index = 0

    def _next(self, question: str) -> object:
        """Retrieve the next scripted answer for a prompt.

        Args:
            question: The prompt text currently being answered.

        Returns:
            The next scripted response value.
        """
        if self._index >= len(self._answers):
            raise AssertionError(f"ScriptedPrompter ran out of answers at: {question!r}")
        answer = self._answers[self._index]
        self._index += 1
        return answer

    def select(self, question: str, choices: Choices, default: str | None = None) -> object:
        """Provide the next scripted value for a selection prompt."""
        return self._next(question)

    def password(self, question: str) -> str:
        """Provide the next scripted value for a password prompt."""
        value = self._next(question)
        return str(value)

    def confirm(self, question: str, default: bool = True) -> bool:
        """Provide the next scripted value for a confirmation prompt."""
        return bool(self._next(question))

    def checkbox(self, question: str, choices: Choices) -> list[object]:
        """Provide the next scripted value for a checkbox prompt."""
        value = self._next(question)
        return list(cast(Any, value)) if value is not None else []

    def text(self, question: str, default: str = "") -> str:
        """Provide the next scripted value for a text prompt."""
        value = self._next(question)
        return "" if value is None else str(value)


async def aprompt[T](fn: Callable[..., T], *args: object, **kwargs: object) -> T:
    """Run a sync prompter call in a worker thread.

    Use inside any ``async def`` that needs to prompt — questionary spins its
    own ``asyncio.run`` internally, which raises ``RuntimeError`` if invoked
    from inside an already-running loop. Off-loading via ``asyncio.to_thread``
    gives questionary a clean thread with no active loop.

    Example::

        choice = await aprompt(prompter.confirm, "Continue?")
    """
    return await asyncio.to_thread(fn, *args, **kwargs)


def _to_questionary_choices(choices: Choices) -> list[str | questionary.Choice]:
    """Bridge to questionary.Choice for dict-style label/value pairs."""
    if isinstance(choices, Mapping):
        return [questionary.Choice(label, value=value) for label, value in choices.items()]
    return list(choices)
