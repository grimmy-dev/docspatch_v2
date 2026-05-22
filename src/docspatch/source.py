"""Source primitives. ``ast`` for analysis, ``libcst`` for mutation."""

import ast
import hashlib
from collections.abc import Iterable
from dataclasses import dataclass

import libcst as cst

from docspatch.cache import FunctionDocState
from docspatch.types.source import FunctionMetadata

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef

MODULE_QUALNAME = "<module>"
"""Qualname used for a file's module-level docstring target."""


# ---- analysis (ast) ---------------------------------------------------------


def scan_functions(source: str) -> dict[str, FunctionDocState]:
    """Map qualname → :class:`FunctionDocState` for each function. Skips nested closures."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    result: dict[str, FunctionDocState] = {}
    _walk_functions(tree, parents=[], out=result)
    return result


def file_hash(source: str) -> str:
    """SHA-256 of raw source. Cheap fast-skip when nothing changed."""
    return hashlib.sha256(source.encode()).hexdigest()


def hash_function(node: FunctionNode) -> str:
    """SHA-256 of the normalized function source, excluding docstring.

    Comments, whitespace, and an existing leading docstring do not affect the
    hash; renames, body changes, and signature changes do.
    """
    normalized = ast.unparse(_strip_docstring(node))
    return hashlib.sha256(normalized.encode()).hexdigest()


def build_signature(node: FunctionNode) -> str:
    """``def name(args) -> Return`` for ``node``."""
    args = _build_args(node.args)
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"{prefix} {node.name}({', '.join(args)}){ret}"


def extract_function_metadata(source: str) -> dict[str, FunctionMetadata]:
    """One ``FunctionMetadata`` per function, keyed by name. Empty on parse failure."""
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
                signature=build_signature(node),
                docstring=ast.get_docstring(node),
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
            )
    return result


def extract_module_docstring(source: str) -> str | None:
    """Module-level docstring, or ``None`` when absent or the file does not parse."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    return ast.get_docstring(tree)


def _walk_functions(node: ast.AST, parents: list[str], out: dict[str, FunctionDocState]) -> None:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            _walk_functions(child, [*parents, child.name], out)
            continue
        if isinstance(child, FunctionNode):
            qualname = ".".join([*parents, child.name])
            out[qualname] = FunctionDocState(
                hash=hash_function(child),
                has_docstring=ast.get_docstring(child) is not None,
                line_start=child.lineno,
            )


def _strip_docstring(node: FunctionNode) -> FunctionNode:
    """Return a shallow copy of ``node`` with any leading docstring removed."""
    if not node.body:
        return node
    first = node.body[0]
    if not (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str)):
        return node
    cls = type(node)
    clone = cls(
        name=node.name,
        args=node.args,
        body=node.body[1:] or [ast.Pass()],
        decorator_list=node.decorator_list,
        returns=node.returns,
        type_comment=node.type_comment,
        type_params=node.type_params,
    )
    ast.copy_location(clone, node)
    ast.fix_missing_locations(clone)
    return clone


def _build_args(fn_args: ast.arguments) -> list[str]:
    """Render args in source order: positional, ``*args``, kw-only, ``**kwargs``."""
    all_args = fn_args.posonlyargs + fn_args.args
    defaults_offset = len(all_args) - len(fn_args.defaults)
    out: list[str] = []
    for i, arg in enumerate(all_args):
        default = ast.unparse(fn_args.defaults[i - defaults_offset]) if i >= defaults_offset else None
        out.append(_render_arg(arg, default))
    if fn_args.vararg:
        out.append(_render_star_arg("*", fn_args.vararg))
    for i, arg in enumerate(fn_args.kwonlyargs):
        kw_default = fn_args.kw_defaults[i]
        default = ast.unparse(kw_default) if kw_default is not None else None
        out.append(_render_arg(arg, default))
    if fn_args.kwarg:
        out.append(_render_star_arg("**", fn_args.kwarg))
    return out


def _render_arg(arg: ast.arg, default: str | None) -> str:
    part = arg.arg
    if arg.annotation:
        part += f": {ast.unparse(arg.annotation)}"
    if default is not None:
        part += f" = {default}"
    return part


def _render_star_arg(prefix: str, arg: ast.arg) -> str:
    part = f"{prefix}{arg.arg}"
    if arg.annotation:
        part += f": {ast.unparse(arg.annotation)}"
    return part


# ---- compression (libcst) ---------------------------------------------------


def compress(source: str) -> str:
    """Replace every function body with ``...``; keep docstrings, module code, comments."""
    if not source.strip():
        return source
    try:
        module = cst.parse_module(source)
    except cst.ParserSyntaxError:
        return source
    return module.visit(_BodyStripper()).code


def estimate_tokens(text: str) -> int:
    """1 token ≈ 4 chars."""
    return len(text) // 4


class _BodyStripper(cst.CSTTransformer):
    """Replace every function body with its docstring (if any) plus ``...``."""

    def leave_FunctionDef(self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef) -> cst.FunctionDef:
        return updated_node.with_changes(body=_stripped_body(updated_node.body))


def _stripped_body(body: cst.BaseSuite) -> cst.BaseSuite:
    if not isinstance(body, cst.IndentedBlock):
        return body
    kept: list[cst.BaseStatement] = []
    if body.body and _is_cst_docstring(body.body[0]):
        kept.append(body.body[0])
    kept.append(cst.SimpleStatementLine(body=[cst.Expr(value=cst.Ellipsis())]))
    return body.with_changes(body=kept)


def _is_cst_docstring(stmt: cst.BaseStatement) -> bool:
    if not isinstance(stmt, cst.SimpleStatementLine) or not stmt.body:
        return False
    first = stmt.body[0]
    return isinstance(first, cst.Expr) and isinstance(first.value, cst.SimpleString | cst.ConcatenatedString)


# ---- insertion (libcst) -----------------------------------------------------


class FunctionNotFoundError(ValueError):
    """Qualname not found in source."""


@dataclass(frozen=True)
class DocstringInsert:
    """``qualname`` should receive ``docstring``."""

    qualname: str
    docstring: str


def insert_docstring(source: str, qualname: str, docstring: str) -> str:
    """Insert one docstring; return new source."""
    return insert_docstrings(source, items=[DocstringInsert(qualname=qualname, docstring=docstring)])


def insert_docstrings(source: str, items: Iterable[DocstringInsert]) -> str:
    """Insert every docstring in ``items`` in one libcst pass.

    Raises:
        FunctionNotFoundError: Any qualname missing from source.
    """
    pending = {item.qualname: item.docstring for item in items}
    if not pending:
        return source
    module = cst.parse_module(source)
    transformer = _DocstringInserter(targets=pending, indent_unit=module.default_indent)
    new_module = module.visit(transformer)
    unmatched = pending.keys() - transformer.matched
    if unmatched:
        raise FunctionNotFoundError(next(iter(unmatched)))
    return new_module.code


class _DocstringInserter(cst.CSTTransformer):
    """Prepend docstrings to functions whose qualname is in ``targets``."""

    def __init__(self, targets: dict[str, str], indent_unit: str) -> None:
        self.targets = targets
        self.indent_unit = indent_unit
        self.path: list[str] = []
        self.matched: set[str] = set()

    def leave_Module(self, original_node: cst.Module, updated_node: cst.Module) -> cst.Module:
        docstring = self.targets.get(MODULE_QUALNAME)
        if docstring is None or MODULE_QUALNAME in self.matched:
            return updated_node
        self.matched.add(MODULE_QUALNAME)
        return updated_node.with_changes(body=_module_body_with_docstring(updated_node.body, docstring))

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        self.path.append(node.name.value)

    def leave_ClassDef(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.ClassDef:
        self.path.pop()
        return updated_node

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        self.path.append(node.name.value)

    def leave_FunctionDef(self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef) -> cst.FunctionDef:
        current = ".".join(self.path)
        depth = len(self.path)
        self.path.pop()
        docstring = self.targets.get(current)
        if docstring is None or current in self.matched:
            return updated_node
        self.matched.add(current)
        body_indent = self.indent_unit * depth
        return updated_node.with_changes(body=_body_with_docstring(updated_node.body, docstring, body_indent))


def _body_with_docstring(body: cst.BaseSuite, docstring: str, body_indent: str) -> cst.BaseSuite:
    if not isinstance(body, cst.IndentedBlock):
        return body
    doc_stmt = _make_docstring_statement(docstring, body_indent)
    statements = list(body.body)
    if statements and _is_cst_docstring(statements[0]):
        statements[0] = doc_stmt
    else:
        statements.insert(0, doc_stmt)
    return body.with_changes(body=statements)


def _module_body_with_docstring(
    body: Iterable[cst.BaseStatement], docstring: str
) -> list[cst.BaseStatement]:
    """Place ``docstring`` at the top of a module, replacing any existing module docstring."""
    doc_stmt = _make_docstring_statement(docstring, "")
    statements = list(body)
    if statements and _is_cst_docstring(statements[0]):
        statements[0] = doc_stmt
    else:
        statements.insert(0, doc_stmt)
    return statements


def _make_docstring_statement(docstring: str, body_indent: str) -> cst.SimpleStatementLine:
    if "\n" not in docstring:
        quoted = f'"""{docstring}"""'
    else:
        inner = _indent_inner_lines(docstring, body_indent)
        quoted = f'"""{inner}\n{body_indent}"""'
    return cst.SimpleStatementLine(body=[cst.Expr(value=cst.SimpleString(value=quoted))])


def _indent_inner_lines(docstring: str, body_indent: str) -> str:
    lines = docstring.split("\n")
    indented = [lines[0]]
    for line in lines[1:]:
        indented.append(f"{body_indent}{line}" if line else "")
    return "\n".join(indented)
