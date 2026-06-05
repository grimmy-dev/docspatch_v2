"""Utilities for AST manipulation, source code compression, docstring extraction, and target injection using LibCST."""

import ast
import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import libcst as cst

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef

MODULE_QUALNAME = "<module>"
"""Qualname used for a file's module-level docstring target."""


# ---- analysis (ast) ---------------------------------------------------------


def file_hash(source: str | bytes) -> str:
    """Compute the SHA-256 hash of raw source code.

    Args:
        source: Source text or byte sequence.

    Returns:
        The hexadecimal hash string.
    """
    data = source if isinstance(source, bytes) else source.encode()
    return hashlib.sha256(data).hexdigest()


def build_signature(node: FunctionNode) -> str:
    """Generate a canonical function signature string from an AST node.

    Args:
        node: The function definition AST node.

    Returns:
        The reconstructed signature string.
    """
    args = _build_args(node.args)
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"{prefix} {node.name}({', '.join(args)}){ret}"


def extract_module_docstring(source: str) -> str | None:
    """Fetch the module-level docstring from a Python source string.

    Args:
        source: The Python source code to parse.

    Returns:
        The extracted docstring text, or None if empty or invalid.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    return ast.get_docstring(tree)


def _build_args(fn_args: ast.arguments) -> list[str]:
    """Convert AST argument structures into a list of formatted strings.

    Args:
        fn_args: The AST argument definition node.

    Returns:
        A list of formatted parameter strings.
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
    """Format a single standard argument into a typed or defaulted string representation.

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
    """Format a variadic parameter with the appropriate star prefix.

    Args:
        prefix: The star prefix (e.g., * or **).
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
    """Minimize source code by stripping non-essential elements using the Squeezer transformer.

    Args:
        source: The raw Python code string to compress.

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
        text: The source content string.

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
        """Remove the module-level docstring during CST transformation.

        Args:
            original_node: The original Module node.
            updated_node: The modified Module node.

        Returns:
            The updated Module node with docstrings removed.
        """
        return updated_node.with_changes(body=strip_docstring(updated_node.body))

    def leave_IndentedBlock(self, original_node: cst.IndentedBlock, updated_node: cst.IndentedBlock) -> cst.IndentedBlock:
        """Remove docstrings and normalize indentation inside block statements.

        Args:
            original_node: The original IndentedBlock node.
            updated_node: The modified IndentedBlock node.

        Returns:
            The updated IndentedBlock node with docstrings removed and indentation normalized.
        """
        body: Sequence[cst.BaseStatement] = strip_docstring(updated_node.body) or [ELLIPSIS_LINE]
        return updated_node.with_changes(body=body, indent=" ")

    def leave_EmptyLine(self, original_node: cst.EmptyLine, updated_node: cst.EmptyLine) -> cst.RemovalSentinel:
        """Remove empty lines from the CST tree.

        Args:
            original_node: The original EmptyLine node.
            updated_node: The modified EmptyLine node.

        Returns:
            A sentinel indicating the node should be removed.
        """
        return cst.RemoveFromParent()

    def leave_TrailingWhitespace(
        self, original_node: cst.TrailingWhitespace, updated_node: cst.TrailingWhitespace
    ) -> cst.TrailingWhitespace:
        """Remove trailing whitespace and comments from the node.

        Args:
            original_node: The original TrailingWhitespace node.
            updated_node: The modified TrailingWhitespace node.

        Returns:
            The updated TrailingWhitespace node with spacing cleared.
        """
        return updated_node.with_changes(whitespace=cst.SimpleWhitespace(""), comment=None)


def strip_docstring[S: cst.BaseStatement](body: Sequence[S]) -> Sequence[S]:
    """Filter out a leading docstring from a sequence of CST statements.

    Args:
        body: A sequence of CST statement nodes.

    Returns:
        The statement sequence with the leading docstring removed.
    """
    if body and is_cst_docstring(body[0]):
        return body[1:]
    return body


def is_cst_docstring(stmt: cst.BaseStatement) -> bool:
    """Check if a CST statement is a simple string literal representing a docstring.

    Args:
        stmt: The statement to evaluate.

    Returns:
        True if the statement is a docstring, False otherwise.
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
        source: The original Python source code.
        qualname: The qualified name of the target node.
        docstring: The docstring content to inject.

    Returns:
        The modified source code with the injected docstring.
    """
    return insert_docstrings(source, items=[DocstringInsert(qualname=qualname, docstring=docstring)])


def insert_docstrings(source: str, items: Iterable[DocstringInsert]) -> str:
    """Inject multiple docstrings simultaneously into Python source code.

    Args:
        source: The original Python source code.
        items: The collection of docstring insertion specifications.

    Returns:
        The modified source code with all docstrings injected.

    Raises:
        FunctionNotFoundError: A qualified name is specified but not found in the source CST.
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
            targets: Map of qualified names to docstring contents.
            indent_unit: Indentation string used for the file.
        """
        self.targets = targets
        self.indent_unit = indent_unit
        self.path: list[str] = []
        self.matched: set[str] = set()

    def leave_Module(self, original_node: cst.Module, updated_node: cst.Module) -> cst.Module:
        """Insert the module-level docstring if specified in target keys.

        Args:
            original_node: The original Module node.
            updated_node: The modified Module node.

        Returns:
            The modified module node with the injected docstring.
        """
        docstring = self.targets.get(MODULE_QUALNAME)
        if docstring is None or MODULE_QUALNAME in self.matched:
            return updated_node
        self.matched.add(MODULE_QUALNAME)
        return updated_node.with_changes(body=_module_body_with_docstring(updated_node.body, docstring))

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        """Register the class name in the current scope path tracker.

        Args:
            node: The ClassDef node being visited.
        """
        self.path.append(node.name.value)

    def leave_ClassDef(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.ClassDef:
        """Pop the class name from the current scope path tracker.

        Args:
            original_node: The original ClassDef node.
            updated_node: The modified ClassDef node.

        Returns:
            The ClassDef node.
        """
        self.path.pop()
        return updated_node

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        """Register the function name in the current scope path tracker.

        Args:
            node: The FunctionDef node being visited.
        """
        self.path.append(node.name.value)

    def leave_FunctionDef(self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef) -> cst.FunctionDef:
        """Insert a matching docstring into the function definition.

        Args:
            original_node: The original FunctionDef node.
            updated_node: The modified FunctionDef node.

        Returns:
            The modified FunctionDef node.
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
    """Prepend or replace a docstring inside an indented CST block.

    Args:
        body: The IndentedBlock or BaseSuite node.
        docstring: The docstring text to insert.
        body_indent: The indentation prefix for inner lines.

    Returns:
        The modified suite node.
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

    Args:
        body: The iterable of module-level statements.
        docstring: The docstring text to insert.

    Returns:
        The list of statements with the docstring at the beginning.
    """
    doc_stmt = _make_docstring_statement(docstring, "")
    statements = list(body)
    if statements and is_cst_docstring(statements[0]):
        statements[0] = doc_stmt
    else:
        statements.insert(0, doc_stmt)
    return statements


def _make_docstring_statement(docstring: str, body_indent: str) -> cst.SimpleStatementLine:
    """Create a CST statement representing a formatted docstring.

    Args:
        docstring: The raw docstring content.
        body_indent: The indentation prefix to apply.

    Returns:
        The statement line node containing the docstring.
    """
    if "\n" not in docstring:
        quoted = f'"""{docstring}"""'
    else:
        inner = _indent_inner_lines(docstring, body_indent)
        quoted = f'"""{inner}\n{body_indent}"""'
    return cst.SimpleStatementLine(body=[cst.Expr(value=cst.SimpleString(value=quoted))])


def _indent_inner_lines(docstring: str, body_indent: str) -> str:
    """Apply the body indentation prefix to all secondary lines of a multiline docstring.

    Args:
        docstring: The multiline docstring.
        body_indent: The indentation prefix.

    Returns:
        The indented docstring text.
    """
    lines = docstring.split("\n")
    indented = [lines[0]]
    for line in lines[1:]:
        indented.append(f"{body_indent}{line}" if line else "")
    return "\n".join(indented)
