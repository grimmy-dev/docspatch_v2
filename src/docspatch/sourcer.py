"""Sourcer deep module — AST-based source analysis. Callers never know which parser is used."""

import ast
import hashlib

from docspatch.types.source import FunctionMetadata


class Sourcer:
    """AST-based source analysis. All methods are stateless."""

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
                sig = _build_signature(node)
                docstring = ast.get_docstring(node)
                result[node.name] = FunctionMetadata(
                    name=node.name,
                    signature=sig,
                    docstring=docstring,
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
        """Strip function bodies, keeping signatures. Returns source with bodies replaced by '...'."""
        if not source.strip():
            return source
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return source

        lines = source.splitlines(keepends=True)
        replacements: list[tuple[int, int, str]] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                body_start = _body_start_line(node, lines)
                body_end = node.end_lineno or node.lineno
                if body_start is not None and body_end >= body_start:
                    indent = _detect_indent(lines[body_start - 1])
                    replacements.append((body_start, body_end, indent + "...\n"))

        if not replacements:
            return source

        # Apply replacements from bottom to top to preserve line numbers
        replacements.sort(key=lambda r: r[0], reverse=True)
        for start, end, stub in replacements:
            lines[start - 1 : end] = [stub]

        return "".join(lines)


def _build_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Reconstruct a human-readable function signature string."""
    args = []
    fn_args = node.args

    # positional-only, regular args, *args, keyword-only, **kwargs
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


def _body_start_line(node: ast.FunctionDef | ast.AsyncFunctionDef, lines: list[str]) -> int | None:
    """Return the 1-based line number where the function body begins (after docstring if present)."""
    if not node.body:
        return None
    first_stmt = node.body[0]
    # Skip docstring
    if (
        isinstance(first_stmt, ast.Expr)
        and isinstance(first_stmt.value, ast.Constant)
        and isinstance(first_stmt.value.value, str)
        and len(node.body) > 1
    ):
        return node.body[1].lineno
    return first_stmt.lineno


def _detect_indent(line: str) -> str:
    """Return the leading whitespace of a line."""
    return line[: len(line) - len(line.lstrip())]
