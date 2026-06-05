"""README tools: public-surface extraction (Tool 2) and body fetch (Tool 3)."""

from pathlib import Path

from docspatch.pipelines.readme.tools import get_file_surface, get_function_body

SAMPLE = '''"""Module doc."""


def public_fn(x: int) -> int:
    """Public."""
    return x + 1


def _private_fn() -> None:
    pass


class Widget:
    """A widget."""

    def method(self) -> str:
        return "hi"
'''


def write(tmp_path: Path, rel: str, src: str) -> Path:
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(src)
    return tmp_path


def test_surface_keeps_public_drops_private(tmp_path: Path) -> None:
    root = write(tmp_path, "pkg/mod.py", SAMPLE)
    surface = get_file_surface(root, "pkg/mod.py")
    assert surface is not None
    assert surface.module_doc == "Module doc."
    names = {(e.kind, e.name) for e in surface.entries}
    assert ("function", "public_fn") in names
    assert ("class", "Widget") in names
    assert ("function", "_private_fn") not in names


def test_surface_carries_signature_and_docstring(tmp_path: Path) -> None:
    root = write(tmp_path, "mod.py", SAMPLE)
    surface = get_file_surface(root, "mod.py")
    assert surface is not None
    fn = next(e for e in surface.entries if e.name == "public_fn")
    assert fn.signature == "def public_fn(x: int) -> int"
    assert fn.docstring == "Public."


def test_surface_missing_file_is_none(tmp_path: Path) -> None:
    assert get_file_surface(tmp_path, "nope.py") is None


def test_surface_syntax_error_is_none(tmp_path: Path) -> None:
    root = write(tmp_path, "bad.py", "def (:\n")
    assert get_file_surface(root, "bad.py") is None


def test_body_compressed_strips_docstring(tmp_path: Path) -> None:
    root = write(tmp_path, "mod.py", SAMPLE)
    body = get_function_body(root, "mod.py", "public_fn")
    assert body is not None
    assert "Public." not in body
    assert "return x + 1" in body


def test_body_finds_nested_method(tmp_path: Path) -> None:
    root = write(tmp_path, "mod.py", SAMPLE)
    body = get_function_body(root, "mod.py", "method")
    assert body is not None
    assert 'return "hi"' in body


def test_body_absent_name_is_none(tmp_path: Path) -> None:
    root = write(tmp_path, "mod.py", SAMPLE)
    assert get_function_body(root, "mod.py", "ghost") is None


def test_body_missing_file_is_none(tmp_path: Path) -> None:
    assert get_function_body(tmp_path, "nope.py", "x") is None
