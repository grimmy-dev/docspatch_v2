"""Sourcer deep module behavior tests (Priority 1)."""

from docspatch.utils.sourcer import Sourcer

_SIMPLE_FUNC = """\
def foo(x: int) -> int:
    return x * 2
"""

_TWO_FUNCS = """\
def foo(x: int) -> int:
    return x * 2

def bar(y: str) -> str:
    return y.upper()
"""

_NO_FUNCS = "x = 1\ny = 2\n"
_EMPTY = ""


def test_python_source_hash_empty_file():
    result = Sourcer.hash(_EMPTY)
    assert isinstance(result, str)
    assert len(result) == 64  # sha256 hex


def test_python_source_hash_no_functions():
    h1 = Sourcer.hash(_NO_FUNCS)
    h2 = Sourcer.hash(_EMPTY)
    assert h1 != h2


def test_python_source_extract_functions_valid():
    result = Sourcer.extract_functions(_TWO_FUNCS)
    assert "foo" in result
    assert "bar" in result
    assert result["foo"].name == "foo"
    assert "x: int" in result["foo"].signature


def test_python_source_extract_functions_empty_for_no_functions():
    result = Sourcer.extract_functions(_NO_FUNCS)
    assert result == {}


def test_python_source_compress_strips_body():
    result = Sourcer.compress(_SIMPLE_FUNC)
    assert "def foo" in result
    assert "return x * 2" not in result


def test_python_source_compress_keeps_signature():
    result = Sourcer.compress(_SIMPLE_FUNC)
    assert "x: int" in result
    assert "int" in result


def test_python_source_compress_preserves_module_comments():
    src = "# top-level comment\nimport os  # inline\n\n# section: helpers\ndef foo(x: int) -> int:\n    return x * 2\n"
    out = Sourcer.compress(src)
    assert "# top-level comment" in out
    assert "# section: helpers" in out
    assert "# inline" in out
    assert "return x * 2" not in out


def test_python_source_compress_keeps_docstring():
    src = 'def foo(x: int) -> int:\n    """Doubles x."""\n    return x * 2\n'
    out = Sourcer.compress(src)
    assert '"""Doubles x."""' in out
    assert "return x * 2" not in out


def test_python_source_compress_handles_async_function():
    src = "async def foo() -> int:\n    await bar()\n    return 1\n"
    out = Sourcer.compress(src)
    assert "async def foo" in out
    assert "await bar()" not in out
    assert "..." in out


def test_python_source_compress_returns_original_on_syntax_error():
    src = "def foo(:\n  pass\n"
    out = Sourcer.compress(src)
    assert out == src


def test_python_source_compress_handles_nested_functions():
    src = "def outer():\n    def inner():\n        return 42\n    return inner\n"
    out = Sourcer.compress(src)
    # Both bodies stripped; nested def header retained as part of outer? With
    # libcst, only the outermost body is stripped — `inner` lives inside `outer`,
    # so the whole nested block collapses to `...`. Either outcome is acceptable
    # as long as the literal return values are gone.
    assert "return 42" not in out
    assert "return inner" not in out
