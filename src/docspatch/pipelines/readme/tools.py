"""Local AST tools the analysis model drives: file surfaces (Tool 2) and function bodies (Tool 3)."""

import ast
from pathlib import Path

from docspatch.pipelines.readme.state import Surface, SurfaceEntry
from docspatch.source import build_signature, compress, extract_module_docstring


def get_file_surface(repo_root: Path, path: str) -> Surface | None:
    """Return a file's public surface: top-level functions and classes, no bodies.

    Tool 2. Private names (leading underscore) and dunder modules are dropped —
    a README documents the public surface. Returns null on a missing or
    unparseable file so the caller can skip it.

    Args:
        repo_root: The repository root.
        path: Repo-relative source path to surface.

    Returns:
        The file's public surface, or null when the file is gone or invalid.
    """
    source = _read(repo_root, path)
    if source is None:
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    entries = [entry for node in tree.body if (entry := _surface_entry(node)) is not None]
    return Surface(path=path, module_doc=extract_module_docstring(source), entries=entries)


def get_function_body(repo_root: Path, path: str, function_name: str) -> str | None:
    """Return the compressed body of a function or method, or null if not found.

    Tool 3. ``compress`` strips docstrings, comments, and blank lines — the same
    reduction the docs pipeline uses — so the generator sees lean implementation.
    Matches the first function with the given name at any nesting (methods
    included). Returns null on a bad fetch (missing file, parse failure, name
    absent) so the caller can skip without retrying.

    Args:
        repo_root: The repository root.
        path: Repo-relative source path.
        function_name: Function or method name to extract.

    Returns:
        The compressed function source, or null when it cannot be fetched.
    """
    source = _read(repo_root, path)
    if source is None:
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == function_name:
            segment = ast.get_source_segment(source, node)
            return compress(segment) if segment else None
    return None


def _surface_entry(node: ast.stmt) -> SurfaceEntry | None:
    """Build a surface entry for a public top-level function or class, else null.

    Returns:
        The entry, or null for private names and non-definition statements.
    """
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and not node.name.startswith("_"):
        return SurfaceEntry("function", node.name, build_signature(node), ast.get_docstring(node))
    if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
        return SurfaceEntry("class", node.name, f"class {node.name}", ast.get_docstring(node))
    return None


def _read(repo_root: Path, path: str) -> str | None:
    """Read a repo-relative source file, returning null when it is missing.

    Returns:
        The file text, or null when the file does not exist or cannot be read.
    """
    try:
        return (repo_root / path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
