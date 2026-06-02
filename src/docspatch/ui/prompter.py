"""Implement an abstraction for terminal user prompts with interactive and scripted modes."""

import asyncio
import os
import sys
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Protocol, cast, runtime_checkable

import questionary

from docspatch.utils.errors import ConfigError

Choices = list[str] | Mapping[str, object]


def is_interactive() -> bool:
    """Check if the current session supports interactive terminal input.

    Returns:
        True if interactive prompts are permitted.
    """
    return sys.stdin.isatty() and not os.environ.get("CI")


@runtime_checkable
class Prompter(Protocol):
    """Interactive question API. Implementations must return concrete values, not chains."""

    def select(self, question: str, choices: Choices, default: str | None = None) -> object:
        """Select an item from a list.

        Returns:
            The selected choice object.
        """
        ...

    def password(self, question: str) -> str:
        """Request a password from the user.

        Returns:
            The string input.
        """
        ...

    def confirm(self, question: str, default: bool = True) -> bool:
        """Ask for a yes or no confirmation.

        Returns:
            True or False based on input.
        """
        ...

    def checkbox(self, question: str, choices: Choices) -> list[object]:
        """Select multiple items from a list.

        Returns:
            A list of selected choice objects.
        """
        ...

    def text(self, question: str, default: str = "") -> str:
        """Input a free-form string.

        Returns:
            The user-provided string.
        """
        ...

    def edit(self, question: str, default: str = "") -> str:
        """Edit a multi-line value seeded with the current text.

        Returns:
            The edited string.
        """
        ...


class QuestionaryPrompter:
    """Real terminal prompter. Returns the selected `value` for dict-style choices.

    In a non-interactive session (piped/CI) questionary would hang forever, so
    each call falls back to its default answer — or aborts when none is safe.
    """

    def select(self, question: str, choices: Choices, default: str | None = None) -> object:
        """Ask a choice-based prompt using the questionary library.

        Returns:
            The chosen value.
        """
        if not is_interactive():
            if default is None:
                raise ConfigError.headless_no_input(question)
            return default
        return questionary.select(question, choices=_to_questionary_choices(choices), default=default).ask()

    def password(self, question: str) -> str:
        """Ask for a password via an interactive hidden input.

        Returns:
            The secret string.
        """
        if not is_interactive():
            raise ConfigError.headless_no_input(question)
        return str(questionary.password(question).ask())

    def confirm(self, question: str, default: bool = True) -> bool:
        """Confirm an action via a boolean prompt.

        Returns:
            The boolean selection.
        """
        if not is_interactive():
            return default
        result = questionary.confirm(question, default=default).ask()
        return bool(result)

    def checkbox(self, question: str, choices: Choices) -> list[object]:
        """Ask the user to select multiple values from a list.

        Returns:
            A list of selected values.
        """
        if not is_interactive():
            return []
        return questionary.checkbox(question, choices=_to_questionary_choices(choices)).ask() or []

    def text(self, question: str, default: str = "") -> str:
        """Ask the user for text input.

        Returns:
            The string input.
        """
        if not is_interactive():
            return default
        result = questionary.text(question, default=default).ask()
        return "" if result is None else str(result)

    def edit(self, question: str, default: str = "") -> str:
        """Edit multi-line text in place, seeded with the current value.

        Returns:
            The edited string, or the default when run headless or cancelled.
        """
        if not is_interactive():
            return default
        result = questionary.text(question, default=default, multiline=True).ask()
        return default if result is None else str(result)


class ScriptedPrompter:
    """Replays answers in order. One answer consumed per call; raises if exhausted."""

    def __init__(self, answers: Iterable[object]) -> None:
        """Initialize a prompter with a scripted sequence of responses."""
        self._answers = list(answers)
        self._index = 0

    def _next(self, question: str) -> object:
        """Fetch the next answer in the sequence.

        Returns:
            The next scripted object.
        """
        if self._index >= len(self._answers):
            raise AssertionError(f"ScriptedPrompter ran out of answers at: {question!r}")
        answer = self._answers[self._index]
        self._index += 1
        return answer

    def select(self, question: str, choices: Choices, default: str | None = None) -> object:
        """Provide a scripted selection choice.

        Returns:
            The scripted choice.
        """
        return self._next(question)

    def password(self, question: str) -> str:
        """Provide a scripted password string.

        Returns:
            The scripted password.
        """
        value = self._next(question)
        return str(value)

    def confirm(self, question: str, default: bool = True) -> bool:
        """Provide a scripted boolean confirmation.

        Returns:
            The scripted boolean value.
        """
        return bool(self._next(question))

    def checkbox(self, question: str, choices: Choices) -> list[object]:
        """Provide a scripted list of choices.

        Returns:
            The scripted selection list.
        """
        value = self._next(question)
        return list(cast(Any, value)) if value is not None else []

    def text(self, question: str, default: str = "") -> str:
        """Provide a scripted text string.

        Returns:
            The scripted string.
        """
        value = self._next(question)
        return "" if value is None else str(value)

    def edit(self, question: str, default: str = "") -> str:
        """Provide a scripted edited string.

        Returns:
            The scripted string, or the default when the scripted value is None.
        """
        value = self._next(question)
        return default if value is None else str(value)


async def aprompt[T](fn: Callable[..., T], *args: object, **kwargs: object) -> T:
    """Run a synchronous prompt function in a worker thread.

    Returns:
        The result of the prompt function.
    """
    return await asyncio.to_thread(fn, *args, **kwargs)


def _to_questionary_choices(choices: Choices) -> list[str | questionary.Choice]:
    """Convert input structures into questionary-compatible choice objects.

    Returns:
        A list of labels or choices.
    """
    if isinstance(choices, Mapping):
        return [questionary.Choice(label, value=value) for label, value in choices.items()]
    return list(choices)
