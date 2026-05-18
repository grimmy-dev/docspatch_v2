"""Error hierarchy behavior tests."""

import pytest

from docspatch.utils.errors import (
    CacheError,
    ConfigError,
    DocspatchError,
    GitError,
    LLMError,
)


def test_docspatch_error_stores_message_and_hint():
    err = DocspatchError("something broke", "try this fix")
    assert err.message == "something broke"
    assert err.hint == "try this fix"


def test_docspatch_error_hint_defaults_to_empty():
    err = DocspatchError("oops")
    assert err.hint == ""


def test_subclasses_are_docspatch_errors():
    for cls in (GitError, ConfigError, LLMError, CacheError):
        err = cls("msg", "hint")
        assert isinstance(err, DocspatchError)
        assert err.message == "msg"
        assert err.hint == "hint"


def test_subclasses_are_exceptions():
    for cls in (DocspatchError, GitError, ConfigError, LLMError, CacheError):
        with pytest.raises(cls):
            raise cls("boom")
