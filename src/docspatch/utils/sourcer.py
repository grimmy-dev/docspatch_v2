"""Sourcer — source analysis.

- `extract_functions` and `hash` use the stdlib `ast` (read-only, fast).
- `compress` uses libcst so module-level comments and blank lines are preserved
  in the LLM prompt context. Existing docstrings are kept; bodies collapse to
  a single `...` statement.

libcst lands here ahead of PRD 02 `insert_docstrings`, which needs the same
round-trip-safe parser to rewrite source without disturbing formatting.
"""

import ast
import hashlib

import libcst as cst

from docspatch.types.source import FunctionMetadata


class Sourcer:
    """Source analysis. All methods are stateless."""

    @staticmethod
    def hash(source: str) -> str:
        """SHA-256 hex digest of source content."""
        return hashlib.sha256(source.encode()).hexdigest()

    @staticmethod
    def extract_functions(source: str) -> dict[str, FunctionMetadata]:
        """Return a map of function name → FunctionMetadata. Empty dict for no functions."""
        if not source.strip():
            return {}
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return {}

        result: dict[str, FunctionMetadata] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                result[node.name] = FunctionMetadata(
                    name=node.name,
                    signature=_build_signature(node),
                    docstring=ast.get_docstring(node),
                    line_start=node.lineno,
                    line_end=node.end_lineno or node.lineno,
                )
        return result

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Rough token estimate: 1 token ≈ 4 characters."""
        return len(text) // 4

    @staticmethod
    def compress(source: str) -> str:
        """Strip function bodies, keeping signatures + docstrings.

        Comments and blank lines outside function bodies are preserved. On
        unparseable input the original source is returned unchanged.
        """
        if not source.strip():
            return source
        try:
            module = cst.parse_module(source)
        except cst.ParserSyntaxError:
            return source
        return module.visit(_BodyStripper()).code


class _BodyStripper(cst.CSTTransformer):
    """Replace every function body with a single `...` (docstring kept if present)."""

    def leave_FunctionDef(self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef) -> cst.FunctionDef:
        return updated_node.with_changes(body=_stripped_body(updated_node.body))


def _stripped_body(body: cst.BaseSuite) -> cst.BaseSuite:
    """Return a body containing only the leading docstring (if any) and `...`."""
    if not isinstance(body, cst.IndentedBlock):
        # `def f(): ...` already collapsed.
        return body

    kept: list[cst.BaseStatement] = []
    if body.body and _is_docstring(body.body[0]):
        kept.append(body.body[0])
    kept.append(cst.SimpleStatementLine(body=[cst.Expr(value=cst.Ellipsis())]))
    return body.with_changes(body=kept)


def _is_docstring(stmt: cst.BaseStatement) -> bool:
    if not isinstance(stmt, cst.SimpleStatementLine) or not stmt.body:
        return False
    first = stmt.body[0]
    return isinstance(first, cst.Expr) and isinstance(first.value, cst.SimpleString | cst.ConcatenatedString)


def _build_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Reconstruct a human-readable function signature string."""
    args = []
    fn_args = node.args

    all_args = fn_args.posonlyargs + fn_args.args
    defaults_offset = len(all_args) - len(fn_args.defaults)

    for i, arg in enumerate(all_args):
        part = arg.arg
        if arg.annotation:
            part += f": {ast.unparse(arg.annotation)}"
        default_idx = i - defaults_offset
        if default_idx >= 0:
            part += f" = {ast.unparse(fn_args.defaults[default_idx])}"
        args.append(part)

    if fn_args.vararg:
        v = fn_args.vararg
        args.append(f"*{v.arg}" + (f": {ast.unparse(v.annotation)}" if v.annotation else ""))

    for i, arg in enumerate(fn_args.kwonlyargs):
        part = arg.arg
        if arg.annotation:
            part += f": {ast.unparse(arg.annotation)}"
        kw_default = fn_args.kw_defaults[i]
        if kw_default is not None:
            part += f" = {ast.unparse(kw_default)}"
        args.append(part)

    if fn_args.kwarg:
        k = fn_args.kwarg
        args.append(f"**{k.arg}" + (f": {ast.unparse(k.annotation)}" if k.annotation else ""))

    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"{prefix} {node.name}({', '.join(args)}){ret}"
