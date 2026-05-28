"""--remarks resolution across fresh runs and resumes."""

from docspatch.pipelines.docs.flags import resolve_remarks
from docspatch.ui.prompter import ScriptedPrompter


def test_fresh_run_uses_requested_remarks() -> None:
    assert resolve_remarks(is_resume=False, prior=None, requested="British", prompter=None) == "British"


def test_fresh_run_without_remarks_is_none() -> None:
    assert resolve_remarks(is_resume=False, prior=None, requested=None, prompter=None) is None


def test_resume_keeps_prior_when_no_new_remarks() -> None:
    assert resolve_remarks(is_resume=True, prior="old", requested=None, prompter=None) == "old"


def test_resume_override_confirmed_uses_new() -> None:
    prompter = ScriptedPrompter([True])
    assert resolve_remarks(is_resume=True, prior="old", requested="new", prompter=prompter) == "new"


def test_resume_override_declined_keeps_prior() -> None:
    prompter = ScriptedPrompter([False])
    assert resolve_remarks(is_resume=True, prior="old", requested="new", prompter=prompter) == "old"
