"""Docstring style guardrails: banned phrases, weak openers, rewrite gate."""

from docspatch.pipelines.docs.docstring_quality import (
    BANNED_PHRASES,
    contains_banned_phrase,
    needs_rewrite,
    opens_with_weak_verb,
)


def test_contains_banned_phrase_case_insensitive() -> None:
    assert contains_banned_phrase("This function returns x.")
    assert contains_banned_phrase("It is responsible for X.")
    assert not contains_banned_phrase("Return the sum of inputs.")


def test_banned_phrase_matches_on_word_boundary() -> None:
    # Whole-phrase meta-tells are caught; incidental substrings are not.
    assert contains_banned_phrase("This method returns the value.")
    assert not contains_banned_phrase("Adjust the frame buffer.")


def test_banned_phrase_constants_stable() -> None:
    assert "this function" in BANNED_PHRASES


def test_weak_opener_checks_first_word_only() -> None:
    assert opens_with_weak_verb("Provide the cached value.")
    assert not opens_with_weak_verb("Resolve and provide the cached value.")


def test_needs_rewrite_combines_both_rules() -> None:
    assert needs_rewrite("Manage the retry loop.")  # weak opener
    assert needs_rewrite("This function runs the loop.")  # banned phrase
    assert not needs_rewrite("Run one LLM call per batch.")
