"""AST parser utility functions to collect, analyze, and measure documentation targets from Python source files."""

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from docspatch.source import (
    MODULE_QUALNAME,
    FunctionNode,
    compress,
    estimate_tokens,
    extract_module_docstring,
    file_hash,
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
        """Estimate the token cost of a code signature and body based on a simple character-to-token ratio.

        Returns:
            An integer representation of estimated token usage.
        """
        return estimate_tokens(self.signature + self.body)


class CollectResult(NamedTuple):
    """Targets needing docstrings, plus how many functions were already documented.

    ``file_hashes`` holds the plan-time raw hash of each file that produced a
    target, captured from the source already read here so the registry need not
    re-read those files.
    """

    targets: list[Target]
    cache_hits: int
    file_hashes: dict[str, str]


def collect_targets(
    paths: Iterable[Path],
    repo_root: Path,
    prev_stamps: dict[str, tuple[int, int]] | None = None,
    *,
    update: bool = False,
) -> CollectResult:
    """Scan paths for modules and functions missing docstrings, skipping files unchanged since the last run.

    Args:
        paths: Python files and directories to inspect.
        repo_root: Directory containing the target repository.
        prev_stamps: Recorded file modification timestamps and sizes from prior runs.
        update: Ignore existing docstrings and unmodified timestamps to force rewrite.

    Returns:
        CollectResult containing the list of targets and a count of documented hits.
    """
    out: list[Target] = []
    cache_hits = 0
    file_hashes: dict[str, str] = {}
    root = repo_root.resolve()
    for path in paths:
        abs_path = path.resolve()
        rel = str(abs_path.relative_to(root))
        # Fast-skip: stat matches the last successful run → file untouched on disk,
        # so its documented/undocumented split is unchanged. No read or parse.
        if not update and prev_stamps is not None:
            try:
                st = abs_path.stat()
            except OSError:
                continue
            if prev_stamps.get(rel) == (st.st_size, st.st_mtime_ns):
                continue
        try:
            source = abs_path.read_text()
        except OSError:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        before = len(out)
        module = module_target(abs_path, rel, source, update=update)
        if module is not None:
            out.append(module)
        source_lines = source.splitlines()
        cache_hits += walk_targets(tree, source_lines, parents=[], file=abs_path, rel=rel, out=out, update=update)
        if len(out) > before:
            file_hashes[rel] = file_hash(source)
    return CollectResult(out, cache_hits, file_hashes)


def module_target(file: Path, rel: str, source: str, *, update: bool) -> Target | None:
    """Create a module-level target when the source file has no module-level docstring.

    Args:
        file: Path to the source file.
        rel: File path relative to repository root.
        source: Raw Python source code contents.
        update: Ignore existing docstrings to force rewrite.

    Returns:
        A Target record for the module, or null if already documented and update is false.
    """
    if not update:
        existing = extract_module_docstring(source)
        if existing is not None and existing.strip():
            return None
    return Target(file=file, rel=rel, qualname=MODULE_QUALNAME, signature=f"module {rel}", body=compress(source))


def walk_targets(
    node: ast.AST,
    source_lines: list[str],
    parents: list[str],
    file: Path,
    rel: str,
    out: list[Target],
    update: bool = False,
) -> int:
    """Traverse the AST recursively to find and extract details of undocumented functions and classes.

    Args:
        node: The current AST node being inspected.
        source_lines: Individual lines of raw source code.
        parents: Stack of parent class and namespace names.
        file: Path to the source file.
        rel: File path relative to repository root.
        out: Accumulator list where new targets are stored.
        update: Ignore existing docstrings to force rewrite.

    Returns:
        Number of targets skipped because they were already documented.
    """
    hits = 0
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            hits += walk_targets(child, source_lines, [*parents, child.name], file, rel, out, update)
            continue
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            if not update:
                existing = ast.get_docstring(child)
                if existing is not None and existing.strip():
                    hits += 1
                    continue
            out.append(
                Target(
                    file=file,
                    rel=rel,
                    qualname=".".join([*parents, child.name]),
                    signature=signature_text(child, source_lines),
                    body=body_text(child, source_lines),
                )
            )
    return hits


def signature_text(node: FunctionNode, source_lines: list[str]) -> str:
    """Extract the signature portion of a function node from raw source lines.

    Args:
        node: AST function definition node.
        source_lines: File source split into lines.

    Returns:
        Textual function signature including decorators, name, parameters, and return annotations.
    """
    start = node.lineno - 1
    body_start = node.body[0].lineno - 1 if node.body else node.lineno
    return "\n".join(source_lines[start:body_start])


def body_text(node: FunctionNode, source_lines: list[str]) -> str:
    """Extract the executable body portion of a function node from raw source lines.

    Args:
        node: AST function definition node.
        source_lines: File source split into lines.

    Returns:
        Source code of the function body lines.
    """
    if not node.body:
        return ""
    start = node.body[0].lineno - 1
    end = node.end_lineno or node.body[-1].end_lineno or start + 1
    return "\n".join(source_lines[start:end])
