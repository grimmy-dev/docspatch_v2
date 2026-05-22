"""Behaviour of source/ helpers (compressor, signatures)."""

import ast

from docspatch.source import (
    build_signature,
    compress,
    estimate_tokens,
    extract_function_metadata,
    extract_module_docstring,
)


def test_extract_module_docstring_returns_text_when_present() -> None:
    assert extract_module_docstring('"""Top of file."""\n\nx = 1\n') == "Top of file."


def test_extract_module_docstring_none_when_absent() -> None:
    assert extract_module_docstring("x = 1\n") is None


def test_extract_module_docstring_none_on_syntax_error() -> None:
    assert extract_module_docstring("def f(") is None


def test_compress_strips_body_and_keeps_docstring() -> None:
    src = 'def f():\n    """Doc."""\n    return 1\n'
    out = compress(src)
    assert '"""Doc."""' in out
    assert "return 1" not in out
    assert "..." in out


def test_compress_returns_unparseable_source_unchanged() -> None:
    src = "def f("
    assert compress(src) == src


def test_compress_keeps_module_level_code() -> None:
    src = "X = 1\n\ndef f():\n    return X\n"
    out = compress(src)
    assert "X = 1" in out
    assert "return X" not in out


def test_estimate_tokens_is_chars_over_four() -> None:
    assert estimate_tokens("a" * 40) == 10


def test_build_signature_with_annotations_and_defaults() -> None:
    node = ast.parse("def f(a: int, b: str = 'x') -> bool: ...").body[0]
    assert isinstance(node, ast.FunctionDef)
    assert build_signature(node) == "def f(a: int, b: str = 'x') -> bool"


def test_build_signature_async_with_star_args() -> None:
    node = ast.parse("async def g(*args, **kwargs): ...").body[0]
    assert isinstance(node, ast.AsyncFunctionDef)
    assert build_signature(node) == "async def g(*args, **kwargs)"


def test_extract_function_metadata_keys_by_name() -> None:
    src = 'def a():\n    """Doc."""\n    return 1\n\ndef b():\n    return 2\n'
    meta = extract_function_metadata(src)
    assert set(meta) == {"a", "b"}
    assert meta["a"].docstring == "Doc."
    assert meta["b"].docstring is None


def test_extract_function_metadata_empty_on_syntax_error() -> None:
    assert extract_function_metadata("def f(") == {}
