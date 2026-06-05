"""Parses source files using python's AST module to extract public interfaces and compress method bodies."""

import ast
from pathlib import Path

from docspatch.pipelines.readme.state import Surface, SurfaceEntry
from docspatch.source import build_signature, compress, extract_module_docstring


def get_file_surface(repo_root: Path, path: str) -> Surface | None:
    """Extract public classes and top-level functions from a source file using AST analysis.

    Args:
        repo_root: The repository root directory path.
        path: The repo-relative path of the target source file.

    Returns:
        The extracted file surface structure, or null on error.
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
    """Extract and compress the source implementation of a target function.

    Args:
        repo_root: The repository root directory path.
        path: The repo-relative path of the target source file.
        function_name: The name of the function to retrieve.

    Returns:
        The compressed source code block, or null if not found.
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
    """Build a surface metadata entry for a public AST node.

    Args:
        node: The AST statement to process.

    Returns:
        The parsed surface entry, or null if the statement is not public.
    """
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and not node.name.startswith("_"):
        return SurfaceEntry("function", node.name, build_signature(node), ast.get_docstring(node))
    if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
        return SurfaceEntry("class", node.name, f"class {node.name}", ast.get_docstring(node))
    return None


def _read(repo_root: Path, path: str) -> str | None:
    """Read a file's content from the local disk using UTF-8 encoding.

    Args:
        repo_root: The repository root directory path.
        path: The repo-relative path to load.

    Returns:
        The full file content, or null if it cannot be read.
    """
    try:
        return (repo_root / path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
