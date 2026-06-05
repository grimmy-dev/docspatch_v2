"""README review loop: accept, revise with accumulating feedback, cancel."""

import pytest

from docspatch.llm import TokenUsage
from docspatch.ui.prompter import ScriptedPrompter
from docspatch.ui.readme_review import ACCEPT, CANCEL, REVISE, review_readme


class _Recorder:
    """Fake regenerate that records the feedback it was called with."""

    def __init__(self):
        self.calls: list[tuple[str, ...]] = []

    async def __call__(self, feedback):
        self.calls.append(feedback)
        return f"DOC{len(self.calls)}", TokenUsage(2, 1)


@pytest.mark.asyncio
async def test_accept_returns_document():
    regen = _Recorder()
    result = await review_readme(ScriptedPrompter([ACCEPT]), regen)
    assert result.accepted is True
    assert result.markdown == "DOC1"
    assert regen.calls == [()]
    assert result.usage == TokenUsage(2, 1)


@pytest.mark.asyncio
async def test_cancel_writes_nothing():
    result = await review_readme(ScriptedPrompter([CANCEL]), _Recorder())
    assert result.accepted is False
    assert result.markdown is None


@pytest.mark.asyncio
async def test_revise_accumulates_feedback_and_sums_usage():
    regen = _Recorder()
    answers = [REVISE, "add install steps", REVISE, "mention license", ACCEPT]
    result = await review_readme(ScriptedPrompter(answers), regen)
    assert result.accepted is True
    assert result.markdown == "DOC3"
    # Feedback grows oldest-first across rounds.
    assert regen.calls == [
        (),
        ("add install steps",),
        ("add install steps", "mention license"),
    ]
    assert result.usage == TokenUsage(6, 3)


@pytest.mark.asyncio
async def test_blank_feedback_does_not_regenerate():
    regen = _Recorder()
    result = await review_readme(ScriptedPrompter([REVISE, "", ACCEPT]), regen)
    assert result.accepted is True
    assert regen.calls == [()]  # blank note skipped, no extra generation
