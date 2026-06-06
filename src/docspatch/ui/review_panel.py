"""Renders and drives the interactive terminal docstring review session."""

from dataclasses import dataclass, field
from pathlib import Path

from rich import box
from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from docspatch.ui.console import console, terminal_size
from docspatch.ui.diff import render_diff
from docspatch.ui.preview import Preview, ReviewEntry, build_file_previews, patchable_by_file
from docspatch.ui.prompter import Prompter

SIDEBAR_MIN_WIDTH = 100
"""Console width at or above which the EXPLORER sidebar renders (only when multi-file)."""

SIDEBAR_COL_WIDTH = 26
"""Fixed column width for the EXPLORER sidebar."""

NAME_TRUNC = 22
"""Max characters shown for one filename in the sidebar tree."""


def short_path(rel: str) -> str:
    """Format a relative file path to show only the parent directory and filename.

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
        """Convert the gathered user decisions and edits into a primitive dictionary.

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
    """Prompt the user to choose whether to skip, overwrite, or abort when a file was changed on disk.

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


def review_session(
    entries: list[dict],
    *,
    repo_root: Path,
    prompter: Prompter,
    allow_rerun: bool,
) -> dict:
    """Run the interactive review UI to gather, cache, and apply docstring decisions.

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
    """Drive the primary interaction loop, prompting for bulk decisions or walking individual entries.

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
    """Prompt the user to decide between bulk acceptance, one-by-one review, or aborting the session.

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
    """Iterate sequentially over remaining entries, presenting action menus and capturing feedback or edits.

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
    """Build the selective mapping of action labels to identifiers based on item validity and settings.

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
    """Print final decision statistics and list any rejected items to the console.

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
    """Construct the combined status line, breadcrumb header, code diff panel, and optional sidebar.

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
    """Assemble the progress header displaying decision counts and the formatted short file path.

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
    """Assemble a breadcrumb text showing the short file path, target qualname, and file-level progress index.

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
    """Build a terminal block displaying a schema-validation error message and raw LLM output.

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


def build_code(*, preview: Preview, max_lines: int = MAX_CODE_LINES) -> Text:
    """Generate a colorized side-by-side or line-based diff and slice it to fit maximum lines.

    Args:
        preview: The unpatched and patched slices for one entry.
        max_lines: Hard cap on rendered rows before a truncation footer.

    Returns:
        The diff view, head-sliced when it overflows the cap.
    """
    diff = render_diff(preview.before, preview.code or "# (preview unavailable)")
    lines = [ln for ln in diff.split("\n") if str(ln)]
    if len(lines) > max_lines:
        # Head slice: signature+docstring sit at the top of the slice, so the
        # change stays visible; reserve one row for the truncation footer.
        kept = lines[: max_lines - 1]
        kept.append(Text(f"# ▾ {len(lines) - len(kept)} more lines", style="dim"))
        lines = kept
    return Text("\n").join(lines)


def build_explorer(files: list[str], *, current: str, max_lines: int | None = None) -> Tree:
    """Build a sidebar tree showing previous files as completed, the current file, and future files.

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
    """Format a single file name row with status icons and dim styles for the sidebar.

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
    """Calculate the allowed height for the file explorer based on terminal dimensions and padding rules.

    Returns:
        Number of rows.
    """
    _, height = terminal_size()
    return max(EXPLORER_MIN_LINES, min(EXPLORER_MAX_LINES, height - EXPLORER_RESERVED_LINES))


def truncate(text: str, width: int) -> str:
    """Crop long text with a leading ellipsis if it exceeds the specified maximum width.

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
    """Extract an ordered file list and group item qualnames under their respective relative paths.

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

