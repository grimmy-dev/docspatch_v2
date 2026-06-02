"""Docs batch-prompt construction: feedback rendering + banned-phrase detection."""

from docspatch.pipelines.docs.prompts import (
    BANNED_PHRASES,
    DocstringItem,
    build_batch_docstring_prompt,
    contains_banned_phrase,
)


def test_prompt_omits_feedback_section_when_empty() -> None:
    item = DocstringItem(key="m.py::foo", signature="def foo():", body="pass")
    prompt = build_batch_docstring_prompt([item], tone="concise")
    assert "Reviewer feedback" not in prompt


def test_prompt_includes_accumulated_feedback_when_present() -> None:
    item = DocstringItem(
        key="m.py::foo",
        signature="def foo():",
        body="pass",
        feedback=("round 1: more detail", "round 2: mention returns"),
    )
    prompt = build_batch_docstring_prompt([item], tone="concise")
    assert "Reviewer feedback" in prompt
    assert "round 1: more detail" in prompt
    assert "round 2: mention returns" in prompt


def test_prompt_omits_remarks_line_when_none() -> None:
    item = DocstringItem(key="m.py::foo", signature="def foo():", body="pass")
    prompt = build_batch_docstring_prompt([item], tone="concise")
    assert "Extra instruction" not in prompt


def test_prompt_includes_remarks_when_given() -> None:
    item = DocstringItem(key="m.py::foo", signature="def foo():", body="pass")
    prompt = build_batch_docstring_prompt([item], tone="concise", remarks="Use British spelling.")
    assert "Use British spelling." in prompt


def test_contains_banned_phrase_case_insensitive() -> None:
    assert contains_banned_phrase("This function returns x.")
    assert contains_banned_phrase("It is responsible for X.")
    assert not contains_banned_phrase("Return the sum of inputs.")


def test_banned_phrase_constants_stable() -> None:
    assert "this function" in BANNED_PHRASES
