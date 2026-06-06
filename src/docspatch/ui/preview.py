"""Builds patched source previews for the docstring review session — no rendering."""

import ast
from dataclasses import dataclass, replace
from pathlib import Path

from docspatch.source import MODULE_QUALNAME, DocstringInsert, FunctionNode, insert_docstrings


@dataclass(frozen=True)
class ReviewEntry:
    """One generated docstring up for review.

    ``parse_failed`` entries carry no usable docstring — ``raw_output`` holds the
    model text for inspection and the entry can only be rerun or rejected.
    """

    rel: str
    qualname: str
    docstring: str
    parse_failed: bool = False
    raw_output: str | None = None

    @property
    def id(self) -> str:
        """Combine the file path and qualified name into a unique identifier key.

        Returns:
            Identifier string formed by relative path and qualified name.
        """
        return f"{self.rel}::{self.qualname}"


@dataclass(frozen=True)
class Preview:
    """Patched source slice for one entry, plus the line where the signature begins.

    ``before`` is the same slice from the unpatched source, so the review can show
    a red/green diff: inserted docstring lines added (green), a replaced one's old
    text removed (red). ``doc_lines`` is the inclusive absolute range of the
    inserted docstring; None when it cannot be resolved.
    """

    code: str
    start_line: int
    doc_lines: tuple[int, int] | None = None
    before: str = ""


def patchable_by_file(entries: list[ReviewEntry]) -> dict[str, list[ReviewEntry]]:
    """Group successful review entries that can be patched, skipping failed parses.

    Args:
        entries: Review entries.

    Returns:
        Mapping of relative path to its patchable entries (parse-failed dropped).
    """
    by_file: dict[str, list[ReviewEntry]] = {}
    for entry in entries:
        if entry.parse_failed:  # no docstring to patch in
            continue
        by_file.setdefault(entry.rel, []).append(entry)
    return by_file


def build_file_previews(repo_root: Path, rel: str, group: list[ReviewEntry]) -> dict[tuple[str, str], Preview]:
    """Patch a single file and slice out original and new previews for all its active entries.

    Args:
        repo_root: Project base directory.
        rel: Relative path of the file.
        group: The file's patchable entries.

    Returns:
        Dictionary mapping identifiers to preview objects.
    """
    path = repo_root / rel
    if not group or not path.exists():
        return {}
    source = path.read_text()
    patched = patch_file(source, group)
    patched_view = _parsed_view(patched)
    if patched_view is None:
        return {}
    # Parse both sources once; every entry slices the same two trees.
    source_view = _parsed_view(source)
    out: dict[tuple[str, str], Preview] = {}
    for entry in group:
        preview = extract_signature_and_docstring(patched_view, entry.qualname)
        if preview is None:
            continue
        # The same slice from the unpatched source is the diff baseline: empty
        # for newly documented code, the old docstring on an --update rewrite.
        original = extract_signature_and_docstring(source_view, entry.qualname) if source_view else None
        out[(entry.rel, entry.qualname)] = replace(preview, before=original.code if original else "")
    return out


def _parsed_view(source: str) -> tuple[ast.Module, list[str]] | None:
    """Parse source once into its AST and line list, or None on syntax error."""
    try:
        return ast.parse(source), source.splitlines()
    except SyntaxError:
        return None


def patch_file(source: str, entries: list[ReviewEntry]) -> str:
    """Apply a list of docstring inserts to the file source, falling back to original code on failure.

    Args:
        source: File text content.
        entries: Docstrings to apply.

    Returns:
        Patched source code string.
    """
    inserts = [DocstringInsert(qualname=e.qualname, docstring=e.docstring) for e in entries]
    try:
        return insert_docstrings(source, items=inserts)
    except Exception:  # noqa: BLE001 — fall back to raw source on parser glitches
        return source


def extract_signature_and_docstring(view: tuple[ast.Module, list[str]], qualname: str) -> Preview | None:
    """Extract the target function signature and docstring from a parsed source view.

    Args:
        view: The source's parsed AST tree paired with its split lines.
        qualname: Qualified function name.

    Returns:
        Preview object or None if the function cannot be resolved.
    """
    tree, lines = view
    if qualname == MODULE_QUALNAME:
        return module_preview(tree, lines)
    func = locate_function(tree, qualname.split("."))
    if func is None:
        return None
    start_line = func.lineno
    end_line = signature_end(func)
    doc_lines: tuple[int, int] | None = None
    if func.body:
        first = func.body[0]
        if is_docstring(first):
            doc_end = first.end_lineno or first.lineno
            end_line = max(end_line, doc_end)
            doc_lines = (first.lineno, doc_end)
    snippet = "\n".join(lines[start_line - 1 : end_line])
    return Preview(code=snippet, start_line=start_line, doc_lines=doc_lines)


def module_preview(tree: ast.Module, lines: list[str]) -> Preview | None:
    """Extract the leading module docstring block from the parsed AST module.

    Returns:
        Preview object or None if no docstring is present.
    """
    if not tree.body or not is_docstring(tree.body[0]):
        return None
    doc = tree.body[0]
    end_line = doc.end_lineno or 1
    snippet = "\n".join(lines[:end_line])
    return Preview(code=snippet, start_line=1, doc_lines=(doc.lineno, end_line))


def locate_function(tree: ast.AST, parts: list[str]) -> FunctionNode | None:
    """Find a specific function node in an AST by recursively resolving nested names.

    Args:
        tree: Root AST node of the module to traverse.
        parts: Ordered sequence of names representing the qualified path to the function.

    Returns:
        The matched function or async function node, or None if not found.
    """
    current: ast.AST = tree
    for i, name in enumerate(parts):
        target_is_leaf = i == len(parts) - 1
        found: ast.AST | None = None
        for child in ast.iter_child_nodes(current):
            if target_is_leaf and isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) and child.name == name:
                return child
            if not target_is_leaf and isinstance(child, ast.ClassDef) and child.name == name:
                found = child
                break
        if found is None:
            return None
        current = found
    return None


def signature_end(func: FunctionNode) -> int:
    """Calculate the ending line number of a function signature in the AST.

    Args:
        func: The AST function node whose signature is being measured.

    Returns:
        The ending line number of the function signature.
    """
    if func.body:
        return max(func.lineno, func.body[0].lineno - 1)
    return func.end_lineno or func.lineno


def is_docstring(node: ast.AST) -> bool:
    """Check whether an AST node is a string literal containing a docstring.

    Args:
        node: The AST node to check.

    Returns:
        True if the node is a constant string expression, False otherwise.
    """
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
