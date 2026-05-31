"""Source primitives. ``ast`` for analysis, ``libcst`` for mutation."""

import ast
import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import libcst as cst

from docspatch.schemas import FunctionDocState, FunctionMetadata

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
    return scan_functions_in(tree)


def scan_functions_in(tree: ast.AST) -> dict[str, FunctionDocState]:
    """Like :func:`scan_functions` but on an already-parsed tree — avoids a re-parse."""
    result: dict[str, FunctionDocState] = {}
    _walk_functions(tree, parents=[], out=result)
    return result


def file_hash(source: str | bytes) -> str:
    """SHA-256 of raw source; accepts bytes to skip encode round-trips."""
    data = source if isinstance(source, bytes) else source.encode()
    return hashlib.sha256(data).hexdigest()


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
    """Traverse the AST to identify functions for documentation state.

    Args:
        node: The current AST node being visited.
        parents: A list of parent scope names.
        out: A dictionary to collect results.
    """
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
    """Format a function argument for a signature.

    Args:
        arg: The argument node from the AST.
        default: The default value as a string if it exists.

    Returns:
        A string representation of the argument.
    """
    part = arg.arg
    if arg.annotation:
        part += f": {ast.unparse(arg.annotation)}"
    if default is not None:
        part += f" = {default}"
    return part


def _render_star_arg(prefix: str, arg: ast.arg) -> str:
    """Format a variable-length argument for a signature.

    Args:
        prefix: The prefix character like * or **.
        arg: The argument node.

    Returns:
        A string representation of the star argument.
    """
    part = f"{prefix}{arg.arg}"
    if arg.annotation:
        part += f": {ast.unparse(arg.annotation)}"
    return part


# ---- compression (libcst) ---------------------------------------------------


def compress(source: str) -> str:
    """Token-lean source: keeps code + names, drops docstrings/comments/blanks,
    one-space indent. Unparseable input returns unchanged.
    """
    if not source.strip():
        return source
    try:
        module = cst.parse_module(source)
    except cst.ParserSyntaxError:
        return source
    return module.visit(Squeezer()).code


def estimate_tokens(text: str) -> int:
    """1 token ≈ 4 chars."""
    return len(text) // 4


ELLIPSIS_LINE = cst.SimpleStatementLine(body=[cst.Expr(value=cst.Ellipsis())])


class Squeezer(cst.CSTTransformer):
    """Squeeze source to a token-lean form, keeping code and identifiers.

    Drops docstrings, comments, and blank lines, and sets each block to one
    space of indentation per level.
    """

    def leave_Module(self, original_node: cst.Module, updated_node: cst.Module) -> cst.Module:
        """Strip the module-level docstring."""
        return updated_node.with_changes(body=strip_docstring(updated_node.body))

    def leave_IndentedBlock(
        self, original_node: cst.IndentedBlock, updated_node: cst.IndentedBlock
    ) -> cst.IndentedBlock:
        """Strip a leading docstring and set one-space indentation."""
        body: Sequence[cst.BaseStatement] = strip_docstring(updated_node.body) or [ELLIPSIS_LINE]
        return updated_node.with_changes(body=body, indent=" ")

    def leave_EmptyLine(
        self, original_node: cst.EmptyLine, updated_node: cst.EmptyLine
    ) -> cst.RemovalSentinel:
        """Drop blank lines and standalone comment lines."""
        return cst.RemoveFromParent()

    def leave_TrailingWhitespace(
        self, original_node: cst.TrailingWhitespace, updated_node: cst.TrailingWhitespace
    ) -> cst.TrailingWhitespace:
        """Drop inline trailing comments."""
        return updated_node.with_changes(whitespace=cst.SimpleWhitespace(""), comment=None)


def strip_docstring[S: cst.BaseStatement](body: Sequence[S]) -> Sequence[S]:
    """Return body without a leading docstring statement, if present."""
    if body and is_cst_docstring(body[0]):
        return body[1:]
    return body


def is_cst_docstring(stmt: cst.BaseStatement) -> bool:
    """Determine if a statement is a valid docstring.

    Args:
        stmt: The statement to check.

    Returns:
        True if the statement is a string expression, False otherwise.
    """
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
        """Initialize the inserter with target docstrings and formatting settings.

        Args:
            targets: Mapping of qualified names to their docstring content.
            indent_unit: The string used for indentation.
        """
        self.targets = targets
        self.indent_unit = indent_unit
        self.path: list[str] = []
        self.matched: set[str] = set()

    def leave_Module(self, original_node: cst.Module, updated_node: cst.Module) -> cst.Module:
        """Insert the module docstring if defined.

        Args:
            original_node: The module node before modification.
            updated_node: The module node being processed.

        Returns:
            The module node with an added docstring.
        """
        docstring = self.targets.get(MODULE_QUALNAME)
        if docstring is None or MODULE_QUALNAME in self.matched:
            return updated_node
        self.matched.add(MODULE_QUALNAME)
        return updated_node.with_changes(body=_module_body_with_docstring(updated_node.body, docstring))

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        """Track the current scope while visiting class definitions.

        Args:
            node: The class node being entered.
        """
        self.path.append(node.name.value)

    def leave_ClassDef(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.ClassDef:
        """Pop the current scope after leaving a class definition.

        Args:
            original_node: The original class node.
            updated_node: The class node being processed.

        Returns:
            The processed class definition node.
        """
        self.path.pop()
        return updated_node

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        """Track the current scope while visiting function definitions.

        Args:
            node: The function node being entered.
        """
        self.path.append(node.name.value)

    def leave_FunctionDef(self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef) -> cst.FunctionDef:
        """Insert a docstring into the function definition if a target exists.

        Args:
            original_node: The original function node.
            updated_node: The function node being processed.

        Returns:
            The function node with the docstring inserted.
        """
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
    """Prepare a body suite to include the generated docstring.

    Args:
        body: The original body suite.
        docstring: The docstring content to inject.
        body_indent: The indentation level for the docstring.

    Returns:
        A suite with the new docstring prepended.
    """
    if not isinstance(body, cst.IndentedBlock):
        return body
    doc_stmt = _make_docstring_statement(docstring, body_indent)
    statements = list(body.body)
    if statements and is_cst_docstring(statements[0]):
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
    if statements and is_cst_docstring(statements[0]):
        statements[0] = doc_stmt
    else:
        statements.insert(0, doc_stmt)
    return statements


def _make_docstring_statement(docstring: str, body_indent: str) -> cst.SimpleStatementLine:
    """Convert a raw docstring string into a CST expression statement.

    Args:
        docstring: The raw docstring text.
        body_indent: The indentation to apply.

    Returns:
        A statement line node containing the docstring.
    """
    if "\n" not in docstring:
        quoted = f'"""{docstring}"""'
    else:
        inner = _indent_inner_lines(docstring, body_indent)
        quoted = f'"""{inner}\n{body_indent}"""'
    return cst.SimpleStatementLine(body=[cst.Expr(value=cst.SimpleString(value=quoted))])


def _indent_inner_lines(docstring: str, body_indent: str) -> str:
    """Apply indentation to lines within a multi-line docstring.

    Args:
        docstring: The raw docstring.
        body_indent: The indentation string.

    Returns:
        The docstring with lines appropriately indented.
    """
    lines = docstring.split("\n")
    indented = [lines[0]]
    for line in lines[1:]:
        indented.append(f"{body_indent}{line}" if line else "")
    return "\n".join(indented)
