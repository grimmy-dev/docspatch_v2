"""Provides interactive prompts, fallback headless behavior, and scripted prompters for test scenarios."""

import asyncio
import os
import sys
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Protocol, cast, runtime_checkable

import questionary

from docspatch.ui.console import console, suspend_timer
from docspatch.utils.errors import ConfigError

Choices = list[str] | Mapping[str, object]


def is_interactive() -> bool:
    """Evaluate if standard input is attached to a TTY and not running in a continuous integration pipeline.

    Returns:
        True if interactive prompts are supported, False otherwise.
    """
    return sys.stdin.isatty() and not os.environ.get("CI")


@runtime_checkable
class Prompter(Protocol):
    """Interactive question API. Implementations must return concrete values, not chains."""

    def select(self, question: str, choices: Choices, default: str | None = None) -> object:
        """Prompt the user to choose an option from a set of choices.

        Args:
            question: The query to present.
            choices: The list or map of possible options.
            default: The preselected fallback option.

        Returns:
            The chosen option.
        """
        ...

    def password(self, question: str) -> str:
        """Prompt the user for sensitive string input with characters hidden.

        Args:
            question: The query to present.

        Returns:
            The entered secret string.
        """
        ...

    def confirm(self, question: str, default: bool = True) -> bool:
        """Prompt the user for a boolean confirmation.

        Args:
            question: The query to present.
            default: The default boolean choice.

        Returns:
            The confirmed answer.
        """
        ...

    def checkbox(self, question: str, choices: Choices) -> list[object]:
        """Prompt the user to select multiple options from a set of choices.

        Args:
            question: The query to present.
            choices: The list or map of options.

        Returns:
            The selected choice objects.
        """
        ...

    def text(self, question: str, default: str = "") -> str:
        """Prompt the user for free-form single-line input.

        Args:
            question: The query to present.
            default: The default input value.

        Returns:
            The text entered.
        """
        ...

    def edit(self, question: str, default: str = "") -> str:
        """Prompt the user to edit a multiline value in a text editor or multiline prompt.

        Args:
            question: The query to present.
            default: The initial multiline content.

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
        """Prompt the user to choose from a list using Questionary or fall back to default when headless.

        Args:
            question: The query to present.
            choices: The list or map of options.
            default: The preselected fallback option.

        Returns:
            The chosen option.

        Raises:
            ConfigError: No interactive console is available and no default is provided.
        """
        if not is_interactive():
            if default is None:
                raise ConfigError.headless_no_input(question)
            return default
        with suspend_timer():
            return questionary.select(question, choices=_to_questionary_choices(choices), default=default).ask()

    def password(self, question: str) -> str:
        """Prompt the user for a password using Questionary, requiring interactive mode.

        Args:
            question: The query to present.

        Returns:
            The hidden string input.

        Raises:
            ConfigError: No interactive console is available.
        """
        if not is_interactive():
            raise ConfigError.headless_no_input(question)
        with suspend_timer():
            return str(questionary.password(question).ask())

    def confirm(self, question: str, default: bool = True) -> bool:
        """Prompt the user for confirmation using Questionary.

        Args:
            question: The query to present.
            default: The default boolean choice.

        Returns:
            The chosen boolean value.
        """
        if not is_interactive():
            return default
        with suspend_timer():
            result = questionary.confirm(question, default=default).ask()
        return bool(result)

    def checkbox(self, question: str, choices: Choices) -> list[object]:
        """Prompt the user to select multiple choices using Questionary.

        Args:
            question: The query to present.
            choices: The options list.

        Returns:
            The list of selected choice objects.
        """
        if not is_interactive():
            return []
        with suspend_timer():
            return questionary.checkbox(question, choices=_to_questionary_choices(choices)).ask() or []

    def text(self, question: str, default: str = "") -> str:
        """Prompt the user for single-line text using Questionary.

        Args:
            question: The query to present.
            default: The default text.

        Returns:
            The entered text.
        """
        if not is_interactive():
            return default
        with suspend_timer():
            result = questionary.text(question, default=default).ask()
        return "" if result is None else str(result)

    def edit(self, question: str, default: str = "") -> str:
        """Prompt the user for multiline text input using Questionary.

        Args:
            question: The query to present.
            default: The default multiline text.

        Returns:
            The resulting multiline string.
        """
        if not is_interactive():
            return default
        with suspend_timer():
            result = questionary.text(question, default=default, multiline=True).ask()
        return default if result is None else str(result)


class ScriptedPrompter:
    """Replays answers in order. One answer consumed per call; raises if exhausted."""

    def __init__(self, answers: Iterable[object]) -> None:
        """Configure the scripted prompter with a predefined list of replies.

        Args:
            answers: The sequence of mock answers to yield.
        """
        self._answers = list(answers)
        self._index = 0

    def _next(self, question: str) -> object:
        """Retrieve the next scripted answer from the sequence.

        Args:
            question: The query associated with this step.

        Returns:
            The scripted answer.

        Raises:
            AssertionError: The prompter runs out of predefined scripted answers.
        """
        if self._index >= len(self._answers):
            raise AssertionError(f"ScriptedPrompter ran out of answers at: {question!r}")
        answer = self._answers[self._index]
        self._index += 1
        return answer

    def select(self, question: str, choices: Choices, default: str | None = None) -> object:
        """Retrieve the next scripted answer for a selection query.

        Args:
            question: The query description.
            choices: The list of potential options.
            default: The default option.

        Returns:
            The scripted answer.
        """
        return self._next(question)

    def password(self, question: str) -> str:
        """Retrieve the next scripted answer as a password.

        Args:
            question: The query description.

        Returns:
            The scripted password string.
        """
        value = self._next(question)
        return str(value)

    def confirm(self, question: str, default: bool = True) -> bool:
        """Retrieve the next scripted answer as a boolean confirmation.

        Args:
            question: The query description.
            default: The default boolean confirmation.

        Returns:
            The scripted boolean answer.
        """
        return bool(self._next(question))

    def checkbox(self, question: str, choices: Choices) -> list[object]:
        """Retrieve the next scripted answer as a list of choices.

        Args:
            question: The query description.
            choices: The list of potential options.

        Returns:
            The list of selected options.
        """
        value = self._next(question)
        return list(cast(Any, value)) if value is not None else []

    def text(self, question: str, default: str = "") -> str:
        """Retrieve the next scripted answer as a single-line string.

        Args:
            question: The query description.
            default: The default text.

        Returns:
            The scripted text.
        """
        value = self._next(question)
        return "" if value is None else str(value)

    def edit(self, question: str, default: str = "") -> str:
        """Retrieve the next scripted answer as an edited multiline string.

        Args:
            question: The query description.
            default: The default text.

        Returns:
            The scripted multiline text.
        """
        value = self._next(question)
        return default if value is None else str(value)


def confirm_or_skip(prompter: Prompter | None, question: str, *, bypass: bool, cancel: str) -> bool:
    """Ask the user to approve an action, or proceed silently when running unattended.

    Args:
        prompter: The interactive prompter, or None when no prompt is possible.
        question: The confirmation question to ask.
        bypass: Skip the prompt and proceed when already gated upstream or headless.
        cancel: Message printed when the user declines.

    Returns:
        True to proceed, False when the user declined.
    """
    if bypass or prompter is None:
        return True
    answer = prompter.confirm(question)
    if not answer:
        console.print(cancel)
    return answer


async def aprompt[T](fn: Callable[..., T], *args: object, **kwargs: object) -> T:
    """Run a synchronous prompter query within a separate executor thread.

    Args:
        fn: The synchronous prompting function.

    Returns:
        The value returned by the prompt function.
    """
    from docspatch.utils.timing import clock

    with clock.paused():
        return await asyncio.to_thread(fn, *args, **kwargs)


def _to_questionary_choices(choices: Choices) -> list[str | questionary.Choice]:
    """Convert choices into a standard list of Questionary Choice objects.

    Args:
        choices: The raw choices list or mapping.

    Returns:
        A list of Questionary-compatible choice options.
    """
    if isinstance(choices, Mapping):
        return [questionary.Choice(label, value=value) for label, value in choices.items()]
    return list(choices)
