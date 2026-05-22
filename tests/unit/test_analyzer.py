"""AST-normalized function hashing. Stability under cosmetic edits is the contract."""

import ast

from docspatch.source import hash_function


def parse_first_function(source: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            return node
    raise AssertionError("no function in source")


def test_whitespace_changes_do_not_change_hash() -> None:
    a = "def f(x):\n    return x + 1\n"
    b = "def f(x):\n\n\n    return x  +  1\n"
    assert hash_function(parse_first_function(a)) == hash_function(parse_first_function(b))


def test_comments_do_not_change_hash() -> None:
    a = "def f(x):\n    return x + 1\n"
    b = "def f(x):\n    # explain\n    return x + 1  # inline\n"
    assert hash_function(parse_first_function(a)) == hash_function(parse_first_function(b))


def test_docstring_does_not_change_hash() -> None:
    a = "def f(x):\n    return x + 1\n"
    b = 'def f(x):\n    """Add one."""\n    return x + 1\n'
    assert hash_function(parse_first_function(a)) == hash_function(parse_first_function(b))


def test_body_change_changes_hash() -> None:
    a = "def f(x):\n    return x + 1\n"
    b = "def f(x):\n    return x + 2\n"
    assert hash_function(parse_first_function(a)) != hash_function(parse_first_function(b))


def test_signature_change_changes_hash() -> None:
    a = "def f(x):\n    return x\n"
    b = "def f(x, y):\n    return x\n"
    assert hash_function(parse_first_function(a)) != hash_function(parse_first_function(b))


def test_rename_changes_hash() -> None:
    a = "def f(x):\n    return x\n"
    b = "def g(x):\n    return x\n"
    assert hash_function(parse_first_function(a)) != hash_function(parse_first_function(b))
