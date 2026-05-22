"""Error hierarchy behavior tests."""

import pytest

from docspatch.utils.errors import (
    EXIT_INTERNAL,
    EXIT_TRANSIENT,
    EXIT_USER_ERROR,
    CacheError,
    ConfigError,
    DocspatchError,
    GitError,
    LLMError,
    LockError,
    ParseFailed,
    PathError,
    TransientExhausted,
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


# --- API-key masking in rendered errors ---


def _render_str(err: DocspatchError, debug: bool = False) -> str:
    from io import StringIO

    from rich.console import Console

    out = StringIO()
    Console(file=out, width=200, no_color=True).print(err.render(debug=debug))
    return out.getvalue()


def test_render_masks_api_key_in_message():
    err = LLMError.api_failure(Exception("401 unauthorized: key sk-ant-abc123def456ghi789 rejected"))
    rendered = _render_str(err)
    assert "sk-ant-abc123def456ghi789" not in rendered
    assert "sk-a••••••••" in rendered


def test_render_masks_secret_context_value():
    err = DocspatchError("config invalid", context={"api_key_anthropic": "sk-ant-supersecretvalue"})
    rendered = _render_str(err, debug=True)
    assert "sk-ant-supersecretvalue" not in rendered


def test_render_leaves_non_secret_text_intact():
    err = DocspatchError("file not found: src/app.py", "pass an existing path")
    rendered = _render_str(err)
    assert "src/app.py" in rendered


def test_render_masks_registered_key_of_unusual_shape():
    """A key the regex shape misses is still masked once registered."""
    from docspatch.utils.secrets import register_secret

    odd_key = "corp-internal-token-Zz9Qx"  # no sk-/AIza prefix — regex misses it
    register_secret(odd_key)
    err = LLMError.api_failure(Exception(f"403 forbidden: token {odd_key} denied"))
    rendered = _render_str(err)
    assert odd_key not in rendered


# --- Error UX: code prefix, context gating, truncation, exit codes ---


def test_render_shows_code_prefix():
    rendered = _render_str(ConfigError("bad value"))
    assert "[docspatch.config]" in rendered


def test_render_hides_context_without_debug():
    err = DocspatchError("oops", context={"path": "src/app.py"})
    assert "src/app.py" not in _render_str(err)


def test_render_shows_context_with_debug():
    err = DocspatchError("oops", context={"path": "src/app.py"})
    assert "src/app.py" in _render_str(err, debug=True)


def test_render_truncates_long_context_value():
    err = DocspatchError("oops", context={"blob": "x" * 500})
    rendered = _render_str(err, debug=True)
    assert "... (truncated)" in rendered
    assert "x" * 500 not in rendered


def test_exit_codes_map_to_error_class():
    assert ConfigError("x").exit_code == EXIT_USER_ERROR
    assert PathError("x").exit_code == EXIT_USER_ERROR
    assert GitError("x").exit_code == EXIT_USER_ERROR
    assert LockError("x").exit_code == EXIT_USER_ERROR
    assert LLMError("x").exit_code == EXIT_TRANSIENT
    assert TransientExhausted("x").exit_code == EXIT_TRANSIENT
    assert ParseFailed("x").exit_code == EXIT_USER_ERROR
    assert CacheError("x").exit_code == EXIT_INTERNAL
