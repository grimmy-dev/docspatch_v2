"""Sourcer deep module behavior tests (Priority 1)."""

from docspatch.sourcer import Sourcer

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
