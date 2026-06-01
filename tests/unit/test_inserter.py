"""Inserter behavior. Tests interact with the public ``insert_docstring`` API only."""

import pytest

from docspatch.source import DocstringInsert, FunctionNotFoundError, insert_docstring, insert_docstrings


def test_top_level_function_gets_docstring() -> None:
    source = "def add(a: int, b: int) -> int:\n    return a + b\n"

    result = insert_docstring(source, qualname="add", docstring="Add a and b.")

    assert result == 'def add(a: int, b: int) -> int:\n    """Add a and b."""\n    return a + b\n'


def test_class_method_docstring_goes_inside_method() -> None:
    source = "class Foo:\n    def bar(self) -> int:\n        return 1\n"

    result = insert_docstring(source, qualname="Foo.bar", docstring="Return one.")

    assert '"""Return one."""' in result
    expected = 'class Foo:\n    def bar(self) -> int:\n        """Return one."""\n        return 1\n'
    assert result == expected


def test_unknown_qualname_raises() -> None:
    source = "def add(a, b): return a + b\n"
    with pytest.raises(FunctionNotFoundError):
        insert_docstring(source, qualname="missing", docstring="x")


def test_multiline_docstring_uses_triple_quotes() -> None:
    source = "def f():\n    return 1\n"

    body = "Do a thing.\n\nReturns:\n    int: Always one."
    result = insert_docstring(source, qualname="f", docstring=body)

    assert '"""Do a thing.' in result
    assert "Returns:" in result
    assert result.count('"""') == 2


def test_multiline_docstring_indented_to_match_body() -> None:
    source = "def f():\n    return 1\n"

    body = "Summary line.\n\nReturns:\n    int: Always one."
    result = insert_docstring(source, qualname="f", docstring=body)

    expected = 'def f():\n    """Summary line.\n\n    Returns:\n        int: Always one.\n    """\n    return 1\n'
    assert result == expected


def test_nested_method_docstring_indented_to_method_body() -> None:
    source = "class C:\n    def m(self) -> None:\n        return None\n"

    body = "Do x.\n\nNotes:\n    Important."
    result = insert_docstring(source, qualname="C.m", docstring=body)

    expected = (
        'class C:\n    def m(self) -> None:\n        """Do x.\n\n        Notes:\n            Important.\n        """\n        return None\n'
    )
    assert result == expected


def test_nested_class_method_addressable_by_full_qualname() -> None:
    source = "class Outer:\n    class Inner:\n        def deep(self) -> None:\n            return None\n"

    result = insert_docstring(source, qualname="Outer.Inner.deep", docstring="Deep one.")

    assert '"""Deep one."""' in result
    assert result.index('"""Deep one."""') > result.index("def deep")


def test_insert_docstrings_writes_many_in_one_pass() -> None:
    source = "def a():\n    return 1\n\n\ndef b():\n    return 2\n"

    result = insert_docstrings(
        source,
        items=[
            DocstringInsert(qualname="a", docstring="Return one."),
            DocstringInsert(qualname="b", docstring="Return two."),
        ],
    )

    assert '"""Return one."""' in result
    assert '"""Return two."""' in result
    assert "return 1" in result
    assert "return 2" in result


def test_insert_docstrings_unknown_qualname_raises() -> None:
    source = "def a():\n    return 1\n"
    with pytest.raises(FunctionNotFoundError):
        insert_docstrings(source, items=[DocstringInsert(qualname="missing", docstring="x")])


def test_insert_docstrings_empty_is_noop() -> None:
    source = "def a():\n    return 1\n"
    assert insert_docstrings(source, items=[]) == source


def test_module_docstring_inserted_at_file_top() -> None:
    source = "import os\n\n\ndef f():\n    return os\n"

    result = insert_docstring(source, qualname="<module>", docstring="Handle paths.")

    assert result == "import os\n\n\ndef f():\n    return os\n".replace("import os", '"""Handle paths."""\nimport os')


def test_module_docstring_replaces_existing() -> None:
    source = '"""Old."""\n\nx = 1\n'

    result = insert_docstring(source, qualname="<module>", docstring="New.")

    assert result == '"""New."""\n\nx = 1\n'


def test_module_and_function_docstrings_in_one_pass() -> None:
    source = "def f():\n    return 1\n"

    result = insert_docstrings(
        source,
        items=[
            DocstringInsert(qualname="<module>", docstring="Mod."),
            DocstringInsert(qualname="f", docstring="Fn."),
        ],
    )

    assert result.startswith('"""Mod."""')
    assert '"""Fn."""' in result


def test_insert_docstrings_handles_class_and_module_methods() -> None:
    source = "class C:\n    def m(self):\n        return 1\n\n\ndef top():\n    return 2\n"

    result = insert_docstrings(
        source,
        items=[
            DocstringInsert(qualname="C.m", docstring="Method."),
            DocstringInsert(qualname="top", docstring="Top fn."),
        ],
    )

    assert '"""Method."""' in result
    assert '"""Top fn."""' in result
