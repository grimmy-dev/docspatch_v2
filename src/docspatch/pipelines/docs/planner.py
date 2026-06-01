"""Scan codebase for functions and modules requiring documentation.
This module traverses files, parses ASTs, and calculates token costs for batch processing."""

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from docspatch.cache import DocsCache
from docspatch.source import (
    MODULE_QUALNAME,
    FunctionNode,
    compress,
    extract_module_docstring,
    scan_functions_in,
)


@dataclass(frozen=True)
class Target:
    """One undocumented function ready for generation."""

    file: Path
    rel: str
    qualname: str
    signature: str
    body: str

    @property
    def token_cost(self) -> int:
        """Compute the token size of the target based on its signature and body.

        Returns:
            Approximate token count.
        """
        return (len(self.signature) + len(self.body)) // 4


class CollectResult(NamedTuple):
    """Targets needing docstrings, plus how many functions a fresh cache skipped."""

    targets: list[Target]
    cache_hits: int


def collect_targets(paths: Iterable[Path], repo_root: Path, cache: DocsCache | None = None, *, update: bool = False) -> CollectResult:
    """Gather functions and modules requiring docstrings while respecting cache state.

    Args:
        paths: File paths to scan.
        repo_root: Absolute path to the repository root.
        cache: Persistent cache for skipping unmodified targets.
        update: Force regeneration of all targets if true.

    Returns:
        Collection of targets and the number of cache-skipped functions.
    """
    out: list[Target] = []
    cache_hits = 0
    root = repo_root.resolve()
    for path in paths:
        abs_path = path.resolve()
        rel = str(abs_path.relative_to(root))
        # Fast-skip: matching size+mtime → cached funcs current, no read/parse.
        if not update and cache is not None:
            try:
                st = abs_path.stat()
            except OSError:
                continue
            cached = cache.get(rel)
            if cached and cached.size == st.st_size and cached.mtime_ns == st.st_mtime_ns:
                cache_hits += sum(1 for fn in cached.functions.values() if fn.has_docstring)
                continue
        try:
            source = abs_path.read_text()
        except OSError:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        module = module_target(abs_path, rel, source, update=update)
        if module is not None:
            out.append(module)
        skip = set() if update else cached_skip_set(rel, tree, cache)
        cache_hits += len(skip)
        source_lines = source.splitlines()
        walk_targets(tree, source_lines, parents=[], file=abs_path, rel=rel, skip=skip, out=out, update=update)
    return CollectResult(out, cache_hits)


def module_target(file: Path, rel: str, source: str, *, update: bool) -> Target | None:
    """Return a module-level target when its documentation is missing.

    Args:
        file: Absolute file path.
        rel: Path relative to repository root.
        source: Raw file content.
        update: Include module regardless of existing documentation if true.

    Returns:
        The module target or null if documented.
    """
    if not update:
        existing = extract_module_docstring(source)
        if existing is not None and existing.strip():
            return None
    return Target(file=file, rel=rel, qualname=MODULE_QUALNAME, signature=f"module {rel}", body=compress(source))


def cached_skip_set(rel: str, tree: ast.AST, cache: DocsCache | None) -> set[str]:
    """Retrieve identifiers for documented functions that match current file state.

    Args:
        rel: Path relative to repository root.
        tree: Parsed AST for the file.
        cache: Persistent documentation cache.

    Returns:
        Set of fully qualified function names to skip.
    """
    if cache is None:
        return set()
    cached = cache.get(rel)
    if cached is None:
        return set()
    current = scan_functions_in(tree)
    return {q for q, fn in current.items() if (prior := cached.functions.get(q)) and prior.hash == fn.hash and prior.has_docstring}


def walk_targets(
    node: ast.AST,
    source_lines: list[str],
    parents: list[str],
    file: Path,
    rel: str,
    skip: set[str],
    out: list[Target],
    update: bool = False,
) -> None:
    """Traverse the AST to identify documentable functions and append them to the target list.

    Args:
        node: AST node to inspect.
        source_lines: Split lines of the source file.
        parents: Ancestry stack for qualified name construction.
        skip: Set of function names that require no action.
        out: List to populate with detected targets.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            walk_targets(child, source_lines, [*parents, child.name], file, rel, skip, out, update)
            continue
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            if not update:
                existing = ast.get_docstring(child)
                if existing is not None and existing.strip():
                    continue
            qualname = ".".join([*parents, child.name])
            if qualname in skip:
                continue
            out.append(
                Target(
                    file=file,
                    rel=rel,
                    qualname=qualname,
                    signature=signature_text(child, source_lines),
                    body=body_text(child, source_lines),
                )
            )


def signature_text(node: FunctionNode, source_lines: list[str]) -> str:
    """Extract the signature lines for an AST node.

    Args:
        node: The function node to examine.
        source_lines: Raw source lines of the file.

    Returns:
        Textual signature.
    """
    start = node.lineno - 1
    body_start = node.body[0].lineno - 1 if node.body else node.lineno
    return "\n".join(source_lines[start:body_start])


def body_text(node: FunctionNode, source_lines: list[str]) -> str:
    """Extract the raw body text from an AST node.

    Args:
        node: The node to extract from.
        source_lines: Raw source lines of the file.

    Returns:
        Textual body.
    """
    if not node.body:
        return ""
    start = node.body[0].lineno - 1
    end = node.end_lineno or node.body[-1].end_lineno or start + 1
    return "\n".join(source_lines[start:end])
