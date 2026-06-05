"""Behaviour of source/ helpers (compressor, signatures)."""

import ast

from docspatch.source import (
    build_signature,
    compress,
    estimate_tokens,
    extract_module_docstring,
)


def test_extract_module_docstring_returns_text_when_present() -> None:
    assert extract_module_docstring('"""Top of file."""\n\nx = 1\n') == "Top of file."


def test_extract_module_docstring_none_when_absent() -> None:
    assert extract_module_docstring("x = 1\n") is None


def test_extract_module_docstring_none_on_syntax_error() -> None:
    assert extract_module_docstring("def f(") is None


def test_compress_keeps_function_body() -> None:
    src = "def f(x):\n    return x * 2\n"
    out = compress(src)
    assert "return x * 2" in out


def test_compress_drops_docstrings() -> None:
    src = 'def f():\n    """Doc here."""\n    return 1\n'
    out = compress(src)
    assert "Doc here." not in out
    assert "return 1" in out


def test_compress_drops_comments() -> None:
    src = "def f():\n    # inline note\n    return 1  # trailing\n"
    out = compress(src)
    assert "note" not in out
    assert "trailing" not in out
    assert "return 1" in out


def test_compress_drops_blank_lines() -> None:
    src = "def f():\n    a = 1\n\n\n    return a\n"
    out = compress(src)
    assert "\n\n" not in out.strip()


def test_compress_reduces_indent_to_one_space() -> None:
    src = "def f():\n    if True:\n        return 1\n"
    out = compress(src)
    assert "\n return 1" not in out  # not a direct child
    assert "\n  return 1" in out  # two levels deep -> 2 spaces


def test_compress_keeps_identifiers_verbatim() -> None:
    src = "def word_stats(text):\n    frequencies = {}\n    return frequencies\n"
    out = compress(src)
    assert "word_stats" in out
    assert "frequencies" in out


def test_compress_preserves_multiline_string_contents() -> None:
    src = 'def q():\n    sql = """\n    SELECT *\n    FROM t\n    """\n    return sql\n'
    out = compress(src)
    assert "    SELECT *\n    FROM t" in out  # literal indentation inside string untouched


def test_compress_returns_unparseable_source_unchanged() -> None:
    src = "def f("
    assert compress(src) == src


def test_compress_keeps_module_level_code() -> None:
    src = "X = 1\n\ndef f():\n    return X\n"
    out = compress(src)
    assert "X = 1" in out
    assert "return X" in out


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
