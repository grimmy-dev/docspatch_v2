"""Defines options for the docstring pipeline and implements validation, feedback resolution, and plan preview calculations."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from docspatch.llm import tier_info
from docspatch.llm.pricing import DOCS_OUTPUT_RATIO, estimate_cost
from docspatch.ui import build_table, console, kv_panel
from docspatch.ui.prompter import Prompter
from docspatch.utils.errors import ConfigError

# ---- RunFlags --------------------------------------------------------------


@dataclass(frozen=True)
class RunFlags:
    """Flags for one ``dp docs`` invocation, plumbed CLI -> command -> graph state."""

    paths: tuple[Path, ...] = ()
    check: bool = False
    update: bool = False
    remarks: str | None = None
    resume: bool = False
    no_ignore: bool = False


# ---- Mutex validation ------------------------------------------------------

# Flag pairs that cannot be combined, with the hint shown on conflict.
_CONFLICTS = (
    ("check", "update", "Preview with --check, then run without it to write."),
    ("check", "remarks", "--remarks affects generation; --check generates nothing."),
    ("check", "resume", "--check starts a fresh preview; it cannot resume a run."),
    ("update", "resume", "A resumed run keeps its scope; --update cannot widen it."),
    ("resume", "path", "A resumed run reuses its original scope — drop the paths."),
)


def validate_run_flags(flags: RunFlags) -> None:
    """Raise a ConfigError if incompatible command-line flags are requested together.

    Args:
        flags: The parsed command-line runtime options.

    Raises:
        ConfigError: Mutually exclusive options like check and update are active simultaneously.
    """
    active = {
        "check": flags.check,
        "update": flags.update,
        "remarks": flags.remarks is not None,
        "resume": flags.resume,
        "path": bool(flags.paths),
    }
    for a, b, hint in _CONFLICTS:
        if active[a] and active[b]:
            raise ConfigError.conflicting_flags(a, b, hint)


# ---- --remarks resolution --------------------------------------------------


def resolve_remarks(*, is_resume: bool, prior: str | None, requested: str | None, prompter: Prompter | None) -> str | None:
    """Select the appropriate instructions to guide docstring generation when resuming an interrupted run.

    Args:
        is_resume: True if resuming a previous run.
        prior: The instructions used during the original run.
        requested: The instructions requested for the current run.
        prompter: User interface prompter to prompt for resolution.

    Returns:
        The chosen instructions string, or None if no instructions are used.
    """
    if not is_resume:
        return requested
    if requested is None or requested == prior:
        return prior
    if prompter is None:
        return requested
    console.print(
        kv_panel(
            "Remarks changed for this resumed run",
            [("Original", prior or "(none)"), ("New", requested)],
            border_style="yellow",
        )
    )
    if prompter.confirm("Use the new remarks instead of the original?"):
        return requested
    return prior


# ---- --check preview -------------------------------------------------------


@dataclass(frozen=True)
class PreviewRow:
    """Per-file line of a ``--check`` preview."""

    rel: str
    functions: int
    input_tokens: int
    cost: float


@dataclass(frozen=True)
class PreviewReport:
    """Undocumented targets grouped by file with estimated tokens and cost.

    Pure value — holds no console. ``rows`` is empty when nothing needs docs.
    """

    rows: list[PreviewRow]
    model: str
    tier: str

    @property
    def any_targets(self) -> bool:
        """Return whether any file has undocumented targets."""
        return bool(self.rows)

    @property
    def total_functions(self) -> int:
        """Return the total undocumented function count across files."""
        return sum(r.functions for r in self.rows)

    @property
    def total_tokens(self) -> int:
        """Return the projected total input tokens across files."""
        return sum(r.input_tokens for r in self.rows)

    @property
    def total_cost(self) -> float:
        """Return the projected total cost across files."""
        return sum(r.cost for r in self.rows)


def analyze_targets(files: list[Path], repo_root: Path, prev_stamps: dict[str, tuple[int, int]], provider: str, tier: str) -> PreviewReport:
    """Estimate the docstring work for undocumented targets, grouped and costed by file.

    Args:
        files: Paths to Python source files to check.
        repo_root: The base directory of the repository.
        prev_stamps: Stored file modification timestamps used to find changes.
        provider: The name of the LLM provider.
        tier: The performance and cost tier of the model.

    Returns:
        A preview report; ``rows`` is empty when nothing needs docs.
    """
    # Deferred: planner pulls libcst via the source module — keep `flags` light
    # so importing it for RunFlags/validation never pays that cost.
    from docspatch.pipelines.docs.planner import Target, collect_targets

    found = collect_targets(files, repo_root, prev_stamps).targets
    by_file: dict[str, list[Target]] = defaultdict(list)
    for target in found:
        by_file[target.rel].append(target)

    rows: list[PreviewRow] = []
    for rel in sorted(by_file):
        items = by_file[rel]
        est = estimate_cost(provider, tier, sum(t.token_cost for t in items), output_ratio=DOCS_OUTPUT_RATIO)
        rows.append(PreviewRow(rel=rel, functions=len(items), input_tokens=est.input_tokens, cost=est.total))
    return PreviewReport(rows=rows, model=tier_info(provider, tier).model, tier=tier)


def preview_check(files: list[Path], repo_root: Path, prev_stamps: dict[str, tuple[int, int]], provider: str, tier: str) -> bool:
    """Print a preview of undocumented targets, token usage, and cost.

    Args:
        files: Paths to Python source files to check.
        repo_root: The base directory of the repository.
        prev_stamps: Stored file modification timestamps used to find changes.
        provider: The name of the LLM provider.
        tier: The performance and cost tier of the model.

    Returns:
        True if any targets require documentation, False otherwise.
    """
    report = analyze_targets(files, repo_root, prev_stamps, provider, tier)
    if not report.any_targets:
        console.print("[green]✓[/green] All Python files documented.")
        return False

    rows = [[r.rel, str(r.functions), f"~{r.input_tokens:,}", f"${r.cost:.4f}"] for r in report.rows]
    rows.append(["TOTAL", str(report.total_functions), f"~{report.total_tokens:,}", f"${report.total_cost:.4f}"])

    console.print(f"[bold]{report.model}[/bold] · {report.tier} tier")
    console.print(build_table(["FILE", "UNDOCUMENTED", "INPUT TOKENS", "COST"], rows))
    console.print(f"[yellow]{report.total_functions} function(s) across {len(report.rows)} file(s) need docstrings.[/yellow]")
    console.print("[dim]Run [/dim]dp docs[dim] to document them.[/dim]")
    return True
