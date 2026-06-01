"""Expose tools for analyzing, hashing, and modifying Python source code through AST and CST manipulation."""

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
    """Map qualname to function state for every top-level and nested function.

    Returns:
        A dictionary of function states keyed by their qualified names.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    return scan_functions_in(tree)


def scan_functions_in(tree: ast.AST) -> dict[str, FunctionDocState]:
    """Execute the scan on a provided AST object tree.

    Args:
        tree: The root node of an existing AST.

    Returns:
        A dictionary of function states keyed by their qualified names.
    """
    result: dict[str, FunctionDocState] = {}
    _walk_functions(tree, parents=[], out=result)
    return result


def file_hash(source: str | bytes) -> str:
    """Compute the SHA-256 hash of raw source code.

    Args:
        source: Source text or byte sequence.

    Returns:
        The hexadecimal hash string.
    """
    data = source if isinstance(source, bytes) else source.encode()
    return hashlib.sha256(data).hexdigest()


def hash_function(node: FunctionNode) -> str:
    """Compute a structural hash of a function, ignoring docstrings and comments.

    Args:
        node: The function definition AST node.

    Returns:
        The hexadecimal hash string.
    """
    normalized = ast.unparse(_strip_docstring(node))
    return hashlib.sha256(normalized.encode()).hexdigest()


def build_signature(node: FunctionNode) -> str:
    """Generate a canonical function signature string from an AST node.

    Args:
        node: The function definition AST node.

    Returns:
        The reconstructed signature.
    """
    args = _build_args(node.args)
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"{prefix} {node.name}({', '.join(args)}){ret}"


def extract_function_metadata(source: str) -> dict[str, FunctionMetadata]:
    """Retrieve metadata including signature and location for all functions.

    Returns:
        A dictionary mapping function names to metadata objects.
    """
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
    """Fetch the module-level docstring from a source string.

    Returns:
        The docstring text or null if absent or invalid.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    return ast.get_docstring(tree)


def _walk_functions(node: ast.AST, parents: list[str], out: dict[str, FunctionDocState]) -> None:
    """Populate the state map by recursing through an AST node.

    Args:
        node: The root node to inspect.
        parents: The current nested scope chain.
        out: The mutable dictionary collecting results.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            _walk_functions(child, [*parents, child.name], out)
            continue
        if isinstance(child, FunctionNode):
            qualname = ".".join([*parents, child.name])
            doc = ast.get_docstring(child)
            out[qualname] = FunctionDocState(
                hash=hash_function(child),
                has_docstring=bool(doc and doc.strip()),
                line_start=child.lineno,
            )


def _strip_docstring(node: FunctionNode) -> FunctionNode:
    """Remove a leading docstring expression from a function body.

    Args:
        node: The original function node.

    Returns:
        The modified function node.
    """
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
    """Convert AST argument structures into a list of formatted strings.

    Args:
        fn_args: The AST argument definition node.

    Returns:
        A list of strings representing each parameter.
    """
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
    """Format a single standard argument into a string.

    Args:
        arg: The AST argument object.
        default: Optional default value expression.

    Returns:
        The formatted argument string.
    """
    part = arg.arg
    if arg.annotation:
        part += f": {ast.unparse(arg.annotation)}"
    if default is not None:
        part += f" = {default}"
    return part


def _render_star_arg(prefix: str, arg: ast.arg) -> str:
    """Format a variadic argument with the appropriate star prefix.

    Args:
        prefix: The prefix (e.g., * or **).
        arg: The AST argument object.

    Returns:
        The formatted star argument string.
    """
    part = f"{prefix}{arg.arg}"
    if arg.annotation:
        part += f": {ast.unparse(arg.annotation)}"
    return part


# ---- compression (libcst) ---------------------------------------------------


def compress(source: str) -> str:
    """Minimize source code by stripping non-essential elements.

    Args:
        source: The raw code string.

    Returns:
        The compressed code string.
    """
    if not source.strip():
        return source
    try:
        module = cst.parse_module(source)
    except cst.ParserSyntaxError:
        return source
    return module.visit(Squeezer()).code


def estimate_tokens(text: str) -> int:
    """Calculate an approximate token count based on string length.

    Args:
        text: The source content.

    Returns:
        The estimated token total.
    """
    return len(text) // 4


ELLIPSIS_LINE = cst.SimpleStatementLine(body=[cst.Expr(value=cst.Ellipsis())])


class Squeezer(cst.CSTTransformer):
    """Squeeze source to a token-lean form, keeping code and identifiers.

    Drops docstrings, comments, and blank lines, and sets each block to one
    space of indentation per level.
    """

    def leave_Module(self, original_node: cst.Module, updated_node: cst.Module) -> cst.Module:
        """Remove the docstring from the module level.

        Returns:
            The updated module node.
        """
        return updated_node.with_changes(body=strip_docstring(updated_node.body))

    def leave_IndentedBlock(self, original_node: cst.IndentedBlock, updated_node: cst.IndentedBlock) -> cst.IndentedBlock:
        """Remove docstrings and normalize indentation to one space.

        Returns:
            The updated indented block.
        """
        body: Sequence[cst.BaseStatement] = strip_docstring(updated_node.body) or [ELLIPSIS_LINE]
        return updated_node.with_changes(body=body, indent=" ")

    def leave_EmptyLine(self, original_node: cst.EmptyLine, updated_node: cst.EmptyLine) -> cst.RemovalSentinel:
        """Remove empty lines from the tree.

        Returns:
            A sentinel for removal.
        """
        return cst.RemoveFromParent()

    def leave_TrailingWhitespace(
        self, original_node: cst.TrailingWhitespace, updated_node: cst.TrailingWhitespace
    ) -> cst.TrailingWhitespace:
        """Remove trailing whitespace and inline comments from statements.

        Returns:
            The updated trailing whitespace node.
        """
        return updated_node.with_changes(whitespace=cst.SimpleWhitespace(""), comment=None)


def strip_docstring[S: cst.BaseStatement](body: Sequence[S]) -> Sequence[S]:
    """Filter out a leading docstring from a sequence of statements.

    Args:
        body: A sequence of AST statements.

    Returns:
        The statement sequence with the docstring removed.
    """
    if body and is_cst_docstring(body[0]):
        return body[1:]
    return body


def is_cst_docstring(stmt: cst.BaseStatement) -> bool:
    """Identify if a statement line is a docstring.

    Args:
        stmt: The statement to check.

    Returns:
        True if the statement is a docstring.
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
    """Insert a docstring into source code for a given qualified name.

    Args:
        source: The original source code.
        qualname: The target scope.
        docstring: The content to insert.

    Returns:
        The source code with the injected docstring.
    """
    return insert_docstrings(source, items=[DocstringInsert(qualname=qualname, docstring=docstring)])


def insert_docstrings(source: str, items: Iterable[DocstringInsert]) -> str:
    """Inject multiple docstrings simultaneously into the source.

    Raises:
        FunctionNotFoundError: A target name is not found in the source tree.
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
        """Configure the docstring insertion transformer.

        Args:
            targets: Map of qualified names to content.
            indent_unit: Indentation string used for the file.
        """
        self.targets = targets
        self.indent_unit = indent_unit
        self.path: list[str] = []
        self.matched: set[str] = set()

    def leave_Module(self, original_node: cst.Module, updated_node: cst.Module) -> cst.Module:
        """Insert the module-level docstring if specified.

        Returns:
            The modified module node.
        """
        docstring = self.targets.get(MODULE_QUALNAME)
        if docstring is None or MODULE_QUALNAME in self.matched:
            return updated_node
        self.matched.add(MODULE_QUALNAME)
        return updated_node.with_changes(body=_module_body_with_docstring(updated_node.body, docstring))

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        """Register the class name in the current path tracker."""
        self.path.append(node.name.value)

    def leave_ClassDef(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.ClassDef:
        """Pop the class name from the path tracker.

        Returns:
            The class definition node.
        """
        self.path.pop()
        return updated_node

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        """Register the function name in the current path tracker."""
        self.path.append(node.name.value)

    def leave_FunctionDef(self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef) -> cst.FunctionDef:
        """Insert a docstring if the current scope matches a target.

        Returns:
            The function definition node.
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
    """Inject a docstring statement into an indented body.

    Returns:
        The updated suite node.
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


def _module_body_with_docstring(body: Iterable[cst.BaseStatement], docstring: str) -> list[cst.BaseStatement]:
    """Prepend a module-level docstring to the statement list.

    Returns:
        The list of statements.
    """
    doc_stmt = _make_docstring_statement(docstring, "")
    statements = list(body)
    if statements and is_cst_docstring(statements[0]):
        statements[0] = doc_stmt
    else:
        statements.insert(0, doc_stmt)
    return statements


def _make_docstring_statement(docstring: str, body_indent: str) -> cst.SimpleStatementLine:
    """Create a CST statement from a docstring string.

    Returns:
        The resulting statement line node.
    """
    if "\n" not in docstring:
        quoted = f'"""{docstring}"""'
    else:
        inner = _indent_inner_lines(docstring, body_indent)
        quoted = f'"""{inner}\n{body_indent}"""'
    return cst.SimpleStatementLine(body=[cst.Expr(value=cst.SimpleString(value=quoted))])


def _indent_inner_lines(docstring: str, body_indent: str) -> str:
    """Apply indentation to all lines of a multi-line string.

    Returns:
        The indented docstring string.
    """
    lines = docstring.split("\n")
    indented = [lines[0]]
    for line in lines[1:]:
        indented.append(f"{body_indent}{line}" if line else "")
    return "\n".join(indented)
