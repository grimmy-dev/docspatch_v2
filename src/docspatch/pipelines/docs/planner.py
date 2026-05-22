"""Collect undocumented functions across files (cache-aware)."""

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from docspatch.cache import DocsCache
from docspatch.source import MODULE_QUALNAME, FunctionNode, compress, scan_functions_in


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
        """1 token ≈ 4 chars of signature + body."""
        return (len(self.signature) + len(self.body)) // 4


class CollectResult(NamedTuple):
    """Targets needing docstrings, plus how many functions a fresh cache skipped."""

    targets: list[Target]
    cache_hits: int


def collect_targets(
    paths: Iterable[Path], repo_root: Path, cache: DocsCache | None = None, *, update: bool = False
) -> CollectResult:
    """Walk each file once and return every function (and module) needing a docstring.

    By default a function is skipped when it already has a docstring or its cached
    hash still matches. ``update`` widens the scope to every function in range,
    bypassing both checks, so existing docstrings are regenerated. ``cache_hits``
    counts functions skipped solely because the cache was fresh.
    """
    out: list[Target] = []
    cache_hits = 0
    root = repo_root.resolve()
    for path in paths:
        abs_path = path.resolve()
        rel = str(abs_path.relative_to(root))
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
        walk_targets(
            tree, source_lines, parents=[], file=abs_path, rel=rel, skip=skip, out=out, update=update
        )
    return CollectResult(out, cache_hits)


def module_target(file: Path, rel: str, source: str, *, update: bool) -> Target | None:
    """Module-docstring target. Module docstrings are (re)generated only under ``--update``."""
    if not update:
        return None
    return Target(file=file, rel=rel, qualname=MODULE_QUALNAME, signature=f"module {rel}", body=compress(source))


def cached_skip_set(rel: str, tree: ast.AST, cache: DocsCache | None) -> set[str]:
    """Qualnames already documented at current hash. Reuses the caller's parsed tree."""
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
    """Recurse the AST; emit each function needing a docstring as a ``Target``.

    ``update`` keeps functions that already have a docstring so they are regenerated.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            walk_targets(child, source_lines, [*parents, child.name], file, rel, skip, out, update)
            continue
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            if not update and ast.get_docstring(child) is not None:
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
    """Signature line(s) as written in the file."""
    start = node.lineno - 1
    body_start = node.body[0].lineno - 1 if node.body else node.lineno
    return "\n".join(source_lines[start:body_start])


def body_text(node: FunctionNode, source_lines: list[str]) -> str:
    """Raw body text as written in the file."""
    if not node.body:
        return ""
    start = node.body[0].lineno - 1
    end = node.end_lineno or node.body[-1].end_lineno or start + 1
    return "\n".join(source_lines[start:end])
