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
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Protocol, cast, runtime_checkable

import questionary

Choices = list[str] | Mapping[str, object]


@runtime_checkable
class Prompter(Protocol):
    """Interactive question API. Implementations must return concrete values, not chains."""

    def select(self, question: str, choices: Choices, default: str | None = None) -> object: ...
    def password(self, question: str) -> str: ...
    def confirm(self, question: str, default: bool = True) -> bool: ...
    def checkbox(self, question: str, choices: Choices) -> list[object]: ...


class QuestionaryPrompter:
    """Real terminal prompter. Returns the selected `value` for dict-style choices."""

    def select(self, question: str, choices: Choices, default: str | None = None) -> object:
        return questionary.select(question, choices=_to_questionary_choices(choices), default=default).ask()

    def password(self, question: str) -> str:
        return str(questionary.password(question).ask())

    def confirm(self, question: str, default: bool = True) -> bool:
        result = questionary.confirm(question, default=default).ask()
        return bool(result)

    def checkbox(self, question: str, choices: Choices) -> list[object]:
        return questionary.checkbox(question, choices=_to_questionary_choices(choices)).ask() or []


class ScriptedPrompter:
    """Replays answers in order. One answer consumed per call; raises if exhausted."""

    def __init__(self, answers: Iterable[object]) -> None:
        self._answers = list(answers)
        self._index = 0

    def _next(self, question: str) -> object:
        if self._index >= len(self._answers):
            raise AssertionError(f"ScriptedPrompter ran out of answers at: {question!r}")
        answer = self._answers[self._index]
        self._index += 1
        return answer

    def select(self, question: str, choices: Choices, default: str | None = None) -> object:
        return self._next(question)

    def password(self, question: str) -> str:
        value = self._next(question)
        return str(value)

    def confirm(self, question: str, default: bool = True) -> bool:
        return bool(self._next(question))

    def checkbox(self, question: str, choices: Choices) -> list[object]:
        value = self._next(question)
        return list(cast(Any, value)) if value is not None else []


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
