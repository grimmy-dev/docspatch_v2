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


def preview_check(files: list[Path], repo_root: Path, prev_stamps: dict[str, tuple[int, int]], provider: str, tier: str) -> bool:
    """Analyze undocumented Python targets and print a preview of expected changes, token usage, and costs.

    Args:
        files: Paths to Python source files to check.
        repo_root: The base directory of the repository.
        prev_stamps: Stored file modification timestamps used to find changes.
        provider: The name of the LLM provider.
        tier: The performance and cost tier of the model.

    Returns:
        True if any targets require documentation, False otherwise.
    """
    # Deferred: planner pulls libcst via the source module — keep `flags` light
    # so importing it for RunFlags/validation never pays that cost.
    from docspatch.pipelines.docs.planner import Target, collect_targets

    found = collect_targets(files, repo_root, prev_stamps).targets
    if not found:
        console.print("[green]✓[/green] All Python files documented.")
        return False

    by_file: dict[str, list[Target]] = defaultdict(list)
    for target in found:
        by_file[target.rel].append(target)

    rows: list[list[str]] = []
    total_fns = total_tokens = 0
    total_cost = 0.0
    for rel in sorted(by_file):
        items = by_file[rel]
        est = estimate_cost(provider, tier, sum(t.token_cost for t in items), output_ratio=DOCS_OUTPUT_RATIO)
        rows.append([rel, str(len(items)), f"~{est.input_tokens:,}", f"${est.total:.4f}"])
        total_fns += len(items)
        total_tokens += est.input_tokens
        total_cost += est.total
    rows.append(["TOTAL", str(total_fns), f"~{total_tokens:,}", f"${total_cost:.4f}"])

    console.print(f"[bold]{tier_info(provider, tier).model}[/bold] · {tier} tier")
    console.print(build_table(["FILE", "UNDOCUMENTED", "INPUT TOKENS", "COST"], rows))
    console.print(f"[yellow]{total_fns} function(s) across {len(by_file)} file(s) need docstrings.[/yellow]")
    console.print("[dim]Run [/dim]dp docs[dim] to document them.[/dim]")
    return True
