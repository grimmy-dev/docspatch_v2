"""Interactive review of generated docstrings before they are committed.

Pure UI: the docs graph pauses on an ``interrupt`` and hands the serialized
entries here; ``review_session`` renders the panels, collects the user's
accept / reject / rerun verdict, and returns it as a plain dict the graph
resumes with. No graph or pipeline imports — the seam stays one-directional.
"""

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
    """Return ``parent/file`` for display."""
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
        """Generate a unique identifier for the review entry."""
        return f"{self.rel}::{self.qualname}"


@dataclass
class Choice:
    """The user's verdict, mirrored straight into the resume dict."""

    accepted: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    rerun: list[str] = field(default_factory=list)
    feedback: dict[str, str] = field(default_factory=dict)
    aborted: bool = False

    def as_dict(self) -> dict:
        """Export the choice attributes as a dictionary."""
        return {
            "accepted": self.accepted,
            "rejected": self.rejected,
            "rerun": self.rerun,
            "feedback": self.feedback,
            "aborted": self.aborted,
        }


CONFLICT_SKIP = "skip"
CONFLICT_FORCE = "force"
CONFLICT_ABORT = "abort"


def prompt_conflict(prompter: Prompter, file: str) -> dict:
    """Ask how to handle a file edited on disk since planning: skip / force / abort."""
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
    """Patched source slice for one entry, plus the line where the signature begins."""

    code: str
    start_line: int


def review_session(
    entries: list[dict],
    *,
    repo_root: Path,
    prompter: Prompter,
    allow_rerun: bool,
) -> dict:
    """Render the review UI for one interrupt payload and return the choice dict.

    Args:
        entries: Serialized docstrings (``rel``, ``qualname``, ``docstring``).
        repo_root: Repo root, used to patch files for the preview.
        prompter: Prompt backend.
        allow_rerun: ``False`` once the rerun-round cap is reached — hides rerun.
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
    previews = build_previews(parsed, repo_root)

    def render(entry: ReviewEntry, ctx: RenderCtx) -> RenderableType:
        preview = previews.get((entry.rel, entry.qualname)) or Preview(code="", start_line=1)
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
    """Drive the accept-all / per-item / abort flow over ``items``."""
    accepted: dict[str, ReviewEntry] = {}
    rejected: dict[str, ReviewEntry] = {}
    rerun: dict[str, ReviewEntry] = {}
    feedback: dict[str, str] = {}

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
    )
    print_summary(outcome, aborted=False)
    return outcome


def top_prompt(prompter: Prompter, *, total: int, remaining_count: int, reviewed_count: int) -> str:
    """Render the top-level menu. First pass uses a clean count; later passes show remaining."""
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
    render,  # noqa: ANN001
    prompter: Prompter,
    total: int,
    already_reviewed: int,
    allow_rerun: bool,
) -> bool:
    """Walk one pass of unreviewed items.

    Returns:
        ``True`` when every item in ``remaining`` was decided, ``False`` when
        the user chose to return to the top menu.
    """
    for offset, item in enumerate(remaining, start=1):
        idx = already_reviewed + offset
        ctx = RenderCtx(idx=idx, total=total, accepted_count=len(accepted), rejected_count=len(rejected))
        console.print(render(item, ctx))
        action = prompter.select(f"[{idx}/{total}] Action?", item_menu(item, allow_rerun=allow_rerun))
        if action == ITEM_ACCEPT:
            accepted[item.id] = item
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
    """Per-item action menu. A parse-failed entry has no acceptable docstring."""
    menu: dict[str, str] = {}
    if not item.parse_failed:
        menu["Accept"] = ITEM_ACCEPT
    menu["Reject"] = ITEM_REJECT
    if allow_rerun:
        menu["Rerun with feedback"] = ITEM_RERUN
    menu["← Back to menu"] = ITEM_BACK
    return menu


def print_summary(outcome: Choice, *, aborted: bool) -> None:
    """Print accept/reject counts plus the rejected ids for an audit trail."""
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
    """Build the full review screen for one pending entry.

    Layout: a thin status line above a single rounded table. The table header
    holds ``EXPLORER`` on the left and a breadcrumb on the right. The single
    body row pairs the file tree with the syntax preview. The sidebar drops out
    when only one file is in scope or the terminal is too narrow.
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
    """Thin status line above the box: progress + accept/reject counts."""
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
    """Header text for the main column: ``📁 dir / file › ◉ qualname (i/N)``."""
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
    """Render banner + raw model output for an entry whose schema validation failed."""
    raw = entry.raw_output or "(no model output captured)"
    return Group(
        Text("⚠ PARSE FAILED — model output did not match the docstring schema", style="bold red"),
        Text("Rerun to try again, or reject to skip this function.", style="dim"),
        Text(""),
        Text(raw, style="dim"),
    )


def build_code(*, preview: Preview, max_lines: int = MAX_CODE_LINES) -> Syntax:
    """Syntax-highlighted signature + inserted docstring; head-slice when over max_lines."""
    raw = preview.code or "# (preview unavailable)"
    lines = raw.splitlines()
    if len(lines) > max_lines:
        # Reserve 1 row for the truncation marker; signature+docstring are
        # at the top of preview.code so a head slice keeps them intact.
        kept = lines[: max_lines - 1]
        elided = len(lines) - len(kept)
        raw = "\n".join([*kept, f"# ▾ {elided} more body lines"])
    return Syntax(
        raw,
        "python",
        line_numbers=True,
        start_line=preview.start_line,
        word_wrap=True,
        background_color="default",
    )


def build_explorer(files: list[str], *, current: str, max_lines: int | None = None) -> Tree:
    """Forward-biased file list: done collapses, current pinned, upcoming fills budget."""
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
    """Render a single row for the file explorer view.

    Args:
        rel: Relative path of the file.
        is_current: Flag indicating if the file is the currently selected one.
    """
    shown = truncate(short_path(rel), NAME_TRUNC)
    if is_current:
        return Text.assemble(("● ", "cyan"), (shown, "bold"))
    return Text(f"  {shown}", style="dim")


def explorer_budget() -> int:
    """Total sidebar rows allowed, clamped to keep the action prompt visible."""
    _, height = terminal_size()
    return max(EXPLORER_MIN_LINES, min(EXPLORER_MAX_LINES, height - EXPLORER_RESERVED_LINES))


def truncate(text: str, width: int) -> str:
    """Truncate with a leading ellipsis so the filename tail stays readable."""
    if len(text) <= width:
        return text
    return "…" + text[-(width - 1) :]


def files_and_siblings(entries: list[ReviewEntry]) -> tuple[list[str], dict[str, list[str]]]:
    """Return the ordered unique file list plus per-file qualname list (spill order preserved)."""
    files: list[str] = []
    siblings: dict[str, list[str]] = {}
    for entry in entries:
        if entry.rel not in siblings:
            files.append(entry.rel)
            siblings[entry.rel] = []
        siblings[entry.rel].append(entry.qualname)
    return files, siblings


def build_previews(entries: list[ReviewEntry], repo_root: Path) -> dict[tuple[str, str], Preview]:
    """Patch each file once; extract the signature+docstring slice per entry."""
    by_file: dict[str, list[ReviewEntry]] = {}
    for entry in entries:
        if entry.parse_failed:  # no docstring to patch in
            continue
        by_file.setdefault(entry.rel, []).append(entry)

    out: dict[tuple[str, str], Preview] = {}
    for rel, group in by_file.items():
        path = repo_root / rel
        if not path.exists():
            continue
        patched = patch_file(path.read_text(), group)
        for entry in group:
            preview = extract_signature_and_docstring(patched, entry.qualname)
            if preview is not None:
                out[(entry.rel, entry.qualname)] = preview
    return out


def patch_file(source: str, entries: list[ReviewEntry]) -> str:
    """Apply every pending docstring for one file in a single libcst pass."""
    inserts = [DocstringInsert(qualname=e.qualname, docstring=e.docstring) for e in entries]
    try:
        return insert_docstrings(source, items=inserts)
    except Exception:  # noqa: BLE001 — fall back to raw source on parser glitches
        return source


def extract_signature_and_docstring(patched_source: str, qualname: str) -> Preview | None:
    """Slice ``patched_source`` to just the function header and its inserted docstring."""
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
    if func.body:
        first = func.body[0]
        if is_docstring(first):
            end_line = max(end_line, first.end_lineno or end_line)
    lines = patched_source.splitlines()
    snippet = "\n".join(lines[start_line - 1 : end_line])
    return Preview(code=snippet, start_line=start_line)


def module_preview(tree: ast.Module, patched_source: str) -> Preview | None:
    """Slice the patched source down to its module docstring."""
    if not tree.body or not is_docstring(tree.body[0]):
        return None
    end_line = tree.body[0].end_lineno or 1
    snippet = "\n".join(patched_source.splitlines()[:end_line])
    return Preview(code=snippet, start_line=1)


def locate_function(tree: ast.AST, parts: list[str]) -> FunctionNode | None:
    """Walk class/def nodes following ``parts`` to find the target function."""
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
    """Last line of the signature (or the line before the body starts)."""
    if func.body:
        return max(func.lineno, func.body[0].lineno - 1)
    return func.end_lineno or func.lineno


def is_docstring(node: ast.AST) -> bool:
    """True if ``node`` is a top-of-body string expression."""
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
