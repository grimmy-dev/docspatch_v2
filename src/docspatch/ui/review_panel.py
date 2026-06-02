"""Manage the interactive review session for generated docstrings."""

import ast
from dataclasses import dataclass, field
from pathlib import Path

from rich import box
from rich.console import Group, RenderableType
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from docspatch.source import MODULE_QUALNAME, DocstringInsert, FunctionNode, insert_docstrings
from docspatch.ui.console import console, terminal_size
from docspatch.ui.prompter import Prompter

SIDEBAR_MIN_WIDTH = 100
"""Console width at or above which the EXPLORER sidebar renders (only when multi-file)."""

SIDEBAR_COL_WIDTH = 26
"""Fixed column width for the EXPLORER sidebar."""

NAME_TRUNC = 22
"""Max characters shown for one filename in the sidebar tree."""


def short_path(rel: str) -> str:
    """Return parent directory and filename for UI display.

    Args:
        rel: Full path string.

    Returns:
        Formatted short path string.
    """
    parts = rel.replace("\\", "/").split("/")
    if len(parts) <= 1:
        return rel
    return f"{parts[-2]}/{parts[-1]}"


EXPLORER_MIN_LINES = 8
EXPLORER_MAX_LINES = 30
EXPLORER_RESERVED_LINES = 12
"""Rows reserved for status, breadcrumb, padding, and the action prompt."""

MAX_CODE_LINES = 50
"""Hard cap on the right-panel code preview height."""

TOP_ACCEPT_ALL = "accept_all"
TOP_REVIEW = "review"
TOP_ABORT = "abort"

ITEM_ACCEPT = "accept"
ITEM_EDIT = "edit"
ITEM_REJECT = "reject"
ITEM_RERUN = "rerun"
ITEM_BACK = "back"


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
        """Generate a unique identifier for the review entry.

        Returns:
            Identifier string formed by relative path and qualified name.
        """
        return f"{self.rel}::{self.qualname}"


@dataclass
class Choice:
    """The user's verdict, mirrored straight into the resume dict.

    ``edited`` maps an accepted entry's id to the user's hand-edited docstring;
    the commit node applies it in place of the generated text.
    """

    accepted: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    rerun: list[str] = field(default_factory=list)
    feedback: dict[str, str] = field(default_factory=dict)
    edited: dict[str, str] = field(default_factory=dict)
    aborted: bool = False

    def as_dict(self) -> dict:
        """Export the choice attributes as a dictionary.

        Returns:
            Dictionary representation of choices.
        """
        return {
            "accepted": self.accepted,
            "rejected": self.rejected,
            "rerun": self.rerun,
            "feedback": self.feedback,
            "edited": self.edited,
            "aborted": self.aborted,
        }


CONFLICT_SKIP = "skip"
CONFLICT_FORCE = "force"
CONFLICT_ABORT = "abort"


def prompt_conflict(prompter: Prompter, file: str) -> dict:
    """Query how to handle a file modified on disk since the run began.

    Args:
        prompter: Interface for user input.
        file: Relative path of the conflicting file.

    Returns:
        Dictionary containing the user's selected action.
    """
    console.print(f"[yellow]⚠ {file} changed on disk since the run started.[/yellow]")
    choices = {
        "Skip this file": CONFLICT_SKIP,
        "Overwrite anyway": CONFLICT_FORCE,
        "Abort the whole commit": CONFLICT_ABORT,
    }
    action = prompter.select(f"{file} — how should docspatch proceed?", choices)
    return {"action": str(action)}


@dataclass(frozen=True)
class Preview:
    """Patched source slice for one entry, plus the line where the signature begins.

    ``doc_lines`` is the inclusive absolute line range of the inserted docstring,
    used to highlight exactly what changed; None when it cannot be resolved.
    """

    code: str
    start_line: int
    doc_lines: tuple[int, int] | None = None


def review_session(
    entries: list[dict],
    *,
    repo_root: Path,
    prompter: Prompter,
    allow_rerun: bool,
) -> dict:
    """Render the review interface and process user choices.

    Args:
        entries: List of docstrings to review.
        repo_root: Base directory for source files.
        prompter: Interface for user input.
        allow_rerun: Toggle visibility of the rerun option.

    Returns:
        Dictionary of accepted, rejected, and rerun decisions.
    """
    parsed = [
        ReviewEntry(
            rel=e["rel"],
            qualname=e["qualname"],
            docstring=e["docstring"],
            parse_failed=e.get("parse_failed", False),
            raw_output=e.get("raw_output"),
        )
        for e in entries
    ]
    if not parsed:
        return Choice().as_dict()

    files, siblings = files_and_siblings(parsed)
    # Build previews per file on first view, not all upfront — a run aborted early
    # then skips the patch/parse work for files never opened.
    entries_by_file = patchable_by_file(parsed)
    preview_cache: dict[tuple[str, str], Preview] = {}
    built: set[str] = set()

    def preview_for(entry: ReviewEntry) -> Preview:
        if entry.rel not in built:
            built.add(entry.rel)
            preview_cache.update(build_file_previews(repo_root, entry.rel, entries_by_file.get(entry.rel, [])))
        return preview_cache.get((entry.rel, entry.qualname)) or Preview(code="", start_line=1)

    def render(entry: ReviewEntry, ctx: RenderCtx) -> RenderableType:
        preview = preview_for(entry)
        return render_review_panel(
            entry=entry,
            ctx=ctx,
            preview=preview,
            files=files,
            siblings=siblings.get(entry.rel, [entry.qualname]),
            console_width=terminal_size()[0],
        )

    choice = run_review(parsed, render=render, prompter=prompter, allow_rerun=allow_rerun)
    return choice.as_dict()


@dataclass(frozen=True)
class RenderCtx:
    """Live counts passed to each render call."""

    idx: int
    total: int
    accepted_count: int
    rejected_count: int


def run_review(
    items: list[ReviewEntry],
    *,
    render,  # noqa: ANN001 — Callable[[ReviewEntry, RenderCtx], RenderableType]
    prompter: Prompter,
    allow_rerun: bool,
) -> Choice:
    """Drive the interaction loop for accepting, rejecting, or rerunning items.

    Args:
        items: List of reviewable entries.
        render: Component for building UI elements.
        prompter: Interface for user input.
        allow_rerun: Toggle availability of rerun actions.

    Returns:
        Choice object containing final session decisions.
    """
    accepted: dict[str, ReviewEntry] = {}
    rejected: dict[str, ReviewEntry] = {}
    rerun: dict[str, ReviewEntry] = {}
    feedback: dict[str, str] = {}
    edited: dict[str, str] = {}

    while True:
        decided = accepted.keys() | rejected.keys() | rerun.keys()
        remaining = [it for it in items if it.id not in decided]
        if not remaining:
            break
        top = top_prompt(
            prompter,
            total=len(items),
            remaining_count=len(remaining),
            reviewed_count=len(items) - len(remaining),
        )
        if top == TOP_ACCEPT_ALL:
            for it in remaining:
                # A parse-failed entry has no docstring to accept — reject it.
                (rejected if it.parse_failed else accepted)[it.id] = it
            break
        if top == TOP_ABORT:
            outcome = Choice(
                accepted=list(accepted),
                rejected=list(rejected),
                rerun=list(rerun),
                feedback=feedback,
                edited=edited,
                aborted=True,
            )
            print_summary(outcome, aborted=True)
            return outcome
        if not walk_items(
            remaining,
            accepted=accepted,
            rejected=rejected,
            rerun=rerun,
            feedback=feedback,
            edited=edited,
            render=render,
            prompter=prompter,
            total=len(items),
            already_reviewed=len(items) - len(remaining),
            allow_rerun=allow_rerun,
        ):
            continue

    outcome = Choice(
        accepted=list(accepted),
        rejected=list(rejected),
        rerun=list(rerun),
        feedback=feedback,
        edited=edited,
    )
    print_summary(outcome, aborted=False)
    return outcome


def top_prompt(prompter: Prompter, *, total: int, remaining_count: int, reviewed_count: int) -> str:
    """Render the main menu, displaying completion progress.

    Args:
        prompter: Interface for user input.
        total: Total number of items.
        remaining_count: Number of pending items.
        reviewed_count: Number of already processed items.

    Returns:
        Selected action string.
    """
    if reviewed_count == 0:
        header = f"{total} docstring(s) generated. Choose how to proceed:"
        accept_label = f"Accept all ({total})"
    else:
        header = f"{remaining_count} remaining · {reviewed_count} already decided. Choose how to proceed:"
        accept_label = f"Accept all remaining ({remaining_count})"
    choices = {accept_label: TOP_ACCEPT_ALL, "Review one by one": TOP_REVIEW, "Abort": TOP_ABORT}
    return str(prompter.select(header, choices))


def walk_items(
    remaining: list[ReviewEntry],
    *,
    accepted: dict[str, ReviewEntry],
    rejected: dict[str, ReviewEntry],
    rerun: dict[str, ReviewEntry],
    feedback: dict[str, str],
    edited: dict[str, str],
    render,  # noqa: ANN001
    prompter: Prompter,
    total: int,
    already_reviewed: int,
    allow_rerun: bool,
) -> bool:
    """Iterate through remaining items for manual review.

    Args:
        remaining: Unreviewed items.
        render: Component for building UI elements.
        prompter: Interface for user input.

    Returns:
        True if the user completed the set, False to return to menu.
    """
    for offset, item in enumerate(remaining, start=1):
        idx = already_reviewed + offset
        ctx = RenderCtx(idx=idx, total=total, accepted_count=len(accepted), rejected_count=len(rejected))
        console.print(render(item, ctx))
        action = prompter.select(f"[{idx}/{total}] Action?", item_menu(item, allow_rerun=allow_rerun))
        if action == ITEM_ACCEPT:
            accepted[item.id] = item
        elif action == ITEM_EDIT:
            new_doc = prompter.edit(f"Edit docstring for {item.qualname}:", default=item.docstring).strip()
            if new_doc and new_doc != item.docstring.strip():
                edited[item.id] = new_doc
            accepted[item.id] = item
            console.print(f"[green]✎ edited · {item.id}[/green]" if item.id in edited else f"[green]✓ accepted · {item.id}[/green]")
        elif action == ITEM_REJECT:
            rejected[item.id] = item
            console.print(f"[yellow]✗ rejected · {item.id}[/yellow]")
        elif action == ITEM_RERUN:
            note = prompter.text(f"Feedback for {item.qualname} (optional, blank to skip):") or ""
            rerun[item.id] = item
            if note:
                feedback[item.id] = note
            console.print(f"[cyan]↻ queued · {item.id}[/cyan]")
        else:
            return False
    return True


def item_menu(item: ReviewEntry, *, allow_rerun: bool) -> dict[str, str]:
    """Construct the action menu for a specific item.

    Args:
        item: Reviewable item.
        allow_rerun: Toggle rerun option.

    Returns:
        Mapping of action labels to identifiers.
    """
    menu: dict[str, str] = {}
    if not item.parse_failed:
        menu["Accept"] = ITEM_ACCEPT
        menu["Edit"] = ITEM_EDIT
    menu["Reject"] = ITEM_REJECT
    if allow_rerun:
        menu["Rerun with feedback"] = ITEM_RERUN
    menu["← Back to menu"] = ITEM_BACK
    return menu


def print_summary(outcome: Choice, *, aborted: bool) -> None:
    """Output the final decision tallies and list rejected entries.

    Args:
        outcome: Collection of user decisions.
        aborted: Status flag for completion.
    """
    label = "Review aborted" if aborted else "Review complete"
    console.print(f"[bold]{label}.[/bold] Accepted {len(outcome.accepted)} · Rejected {len(outcome.rejected)}")
    if outcome.rejected:
        console.print("[dim]Rejected:[/dim]")
        for rid in outcome.rejected:
            console.print(f"  [yellow]✗[/yellow] {rid}")


def render_review_panel(
    *,
    entry: ReviewEntry,
    ctx: RenderCtx,
    preview: Preview,
    files: list[str],
    siblings: list[str],
    console_width: int,
) -> RenderableType:
    """Assemble the full screen layout for one review entry.

    Args:
        entry: Current item.
        preview: Syntax-highlighted code preview.
        files: All files in scope.
        siblings: Related items in current file.
        console_width: Terminal dimensions.

    Returns:
        Renderable UI container.
    """
    status = build_status(entry=entry, ctx=ctx)
    breadcrumb = build_breadcrumb(entry=entry, siblings=siblings)
    code = build_parse_fail_body(entry) if entry.parse_failed else build_code(preview=preview)
    show_sidebar = len(files) > 1 and console_width >= SIDEBAR_MIN_WIDTH

    table = Table(
        box=box.ROUNDED,
        show_header=True,
        show_lines=False,
        expand=True,
        padding=(0, 1),
        border_style="cyan",
    )
    if show_sidebar:
        tree = build_explorer(files, current=entry.rel)
        table.add_column(Text("📂 EXPLORER", style="bold"), width=SIDEBAR_COL_WIDTH, no_wrap=True)
        table.add_column(breadcrumb, ratio=1, overflow="fold")
        table.add_row(tree, code)
    else:
        table.add_column(breadcrumb, ratio=1, overflow="fold")
        table.add_row(code)
    return Group(status, table)


def build_status(*, entry: ReviewEntry, ctx: RenderCtx) -> Text:
    """Generate the status line displaying review progress and counts.

    Returns:
        Formatted progress text.
    """
    return Text.assemble(
        ("Review ", "bold"),
        (f"{ctx.idx}/{ctx.total}", "bold cyan"),
        "   ",
        ("✓ ", "green"),
        (f"{ctx.accepted_count}", "green"),
        "   ",
        ("✗ ", "red"),
        (f"{ctx.rejected_count}", "red"),
        "   ",
        (f"· {short_path(entry.rel)}", "dim"),
    )


def build_breadcrumb(*, entry: ReviewEntry, siblings: list[str]) -> Text:
    """Generate header text for the item context.

    Returns:
        Formatted breadcrumb text.
    """
    try:
        in_file = siblings.index(entry.qualname) + 1
    except ValueError:
        in_file = 1
    return Text.assemble(
        ("📁 ", "yellow"),
        (short_path(entry.rel), "bold"),
        ("  › ", "dim"),
        ("◉ ", "cyan"),
        (f"{entry.qualname}()", "bold cyan"),
        ("   "),
        (f"({in_file}/{len(siblings) or 1} in file)", "dim"),
    )


def build_parse_fail_body(entry: ReviewEntry) -> RenderableType:
    """Create a display for entries that failed schema validation.

    Args:
        entry: Entry containing raw output.

    Returns:
        UI group with error message and raw output.
    """
    raw = entry.raw_output or "(no model output captured)"
    return Group(
        Text("⚠ PARSE FAILED — model output did not match the docstring schema", style="bold red"),
        Text("Rerun to try again, or reject to skip this function.", style="dim"),
        Text(""),
        Text(raw, style="dim"),
    )


def build_code(*, preview: Preview, max_lines: int = MAX_CODE_LINES) -> Syntax:
    """Highlight the code snippet with the new docstring.

    Args:
        preview: Code object.

    Returns:
        Syntax-highlighted display component.
    """
    raw = preview.code or "# (preview unavailable)"
    lines = raw.splitlines()
    if len(lines) > max_lines:
        # Reserve 1 row for the truncation marker; signature+docstring are
        # at the top of preview.code so a head slice keeps them intact.
        kept = lines[: max_lines - 1]
        elided = len(lines) - len(kept)
        raw = "\n".join([*kept, f"# ▾ {elided} more body lines"])
    # Highlight the inserted docstring so the reviewer sees exactly what changed.
    highlight = set(range(preview.doc_lines[0], preview.doc_lines[1] + 1)) if preview.doc_lines else set()
    return Syntax(
        raw,
        "python",
        line_numbers=True,
        start_line=preview.start_line,
        word_wrap=True,
        background_color="default",
        highlight_lines=highlight,
    )


def build_explorer(files: list[str], *, current: str, max_lines: int | None = None) -> Tree:
    """Create the sidebar tree for file navigation.

    Args:
        files: Ordered files list.
        current: Currently selected file.

    Returns:
        Rich tree object.
    """
    budget = max_lines if max_lines is not None else explorer_budget()
    try:
        idx = files.index(current)
    except ValueError:
        idx = 0
    done_count = idx
    upcoming = files[idx:]

    tree = Tree("", hide_root=True, guide_style="dim")
    if done_count:
        tree.add(Text(f"✓ {done_count} done", style="dim green"))

    rows_for_files = max(1, budget - (1 if done_count else 0))
    if len(upcoming) <= rows_for_files:
        for i, f in enumerate(upcoming):
            tree.add(_explorer_row(f, is_current=(i == 0)))
        return tree

    # Overflow: reserve 1 row for the "▾ N more" footer.
    visible = max(1, rows_for_files - 1)
    for i, f in enumerate(upcoming[:visible]):
        tree.add(_explorer_row(f, is_current=(i == 0)))
    hidden = len(upcoming) - visible
    tree.add(Text(f"▾ {hidden} more upcoming", style="dim"))
    return tree


def _explorer_row(rel: str, *, is_current: bool) -> Text:
    """Format a single file row for the sidebar.

    Args:
        rel: Relative path.
        is_current: Toggle current status styling.

    Returns:
        Formatted text element.
    """
    shown = truncate(short_path(rel), NAME_TRUNC)
    if is_current:
        return Text.assemble(("● ", "cyan"), (shown, "bold"))
    return Text(f"  {shown}", style="dim")


def explorer_budget() -> int:
    """Calculate allowed sidebar rows based on terminal height.

    Returns:
        Number of rows.
    """
    _, height = terminal_size()
    return max(EXPLORER_MIN_LINES, min(EXPLORER_MAX_LINES, height - EXPLORER_RESERVED_LINES))


def truncate(text: str, width: int) -> str:
    """Truncate text with a leading ellipsis.

    Args:
        text: Original string.
        width: Maximum character count.

    Returns:
        Truncated string.
    """
    if len(text) <= width:
        return text
    return "…" + text[-(width - 1) :]


def files_and_siblings(entries: list[ReviewEntry]) -> tuple[list[str], dict[str, list[str]]]:
    """Organize entries into a list of files and mapping of items.

    Returns:
        Files list and a dictionary of item names per file.
    """
    files: list[str] = []
    siblings: dict[str, list[str]] = {}
    for entry in entries:
        if entry.rel not in siblings:
            files.append(entry.rel)
            siblings[entry.rel] = []
        siblings[entry.rel].append(entry.qualname)
    return files, siblings


def patchable_by_file(entries: list[ReviewEntry]) -> dict[str, list[ReviewEntry]]:
    """Group entries that carry a docstring by their file.

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
    """Generate code previews for one file's entries by patching it once.

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
    patched = patch_file(path.read_text(), group)
    out: dict[tuple[str, str], Preview] = {}
    for entry in group:
        preview = extract_signature_and_docstring(patched, entry.qualname)
        if preview is not None:
            out[(entry.rel, entry.qualname)] = preview
    return out


def patch_file(source: str, entries: list[ReviewEntry]) -> str:
    """Insert all pending docstrings into file source code.

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


def extract_signature_and_docstring(patched_source: str, qualname: str) -> Preview | None:
    """Extract a function signature and docstring from the patched source code.

    Args:
        patched_source: Full file source after patching.
        qualname: Qualified function name.

    Returns:
        Preview object or None if the function cannot be resolved.
    """
    try:
        tree = ast.parse(patched_source)
    except SyntaxError:
        return None
    if qualname == MODULE_QUALNAME:
        return module_preview(tree, patched_source)
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
    lines = patched_source.splitlines()
    snippet = "\n".join(lines[start_line - 1 : end_line])
    return Preview(code=snippet, start_line=start_line, doc_lines=doc_lines)


def module_preview(tree: ast.Module, patched_source: str) -> Preview | None:
    """Extract the module docstring from the source tree.

    Returns:
        Preview object or None if no docstring is present.
    """
    if not tree.body or not is_docstring(tree.body[0]):
        return None
    doc = tree.body[0]
    end_line = doc.end_lineno or 1
    snippet = "\n".join(patched_source.splitlines()[:end_line])
    return Preview(code=snippet, start_line=1, doc_lines=(doc.lineno, end_line))


def locate_function(tree: ast.AST, parts: list[str]) -> FunctionNode | None:
    """Locate an AST node by traversing a chain of names.

    Args:
        tree: Root module AST.
        parts: List of qualification parts.

    Returns:
        Target function node or None.
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
    """Determine the line number marking the end of a signature.

    Returns:
        Ending line integer.
    """
    if func.body:
        return max(func.lineno, func.body[0].lineno - 1)
    return func.end_lineno or func.lineno


def is_docstring(node: ast.AST) -> bool:
    """Verify if a node is a module-level or function-level docstring expression.

    Args:
        node: AST node.

    Returns:
        Boolean result.
    """
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
