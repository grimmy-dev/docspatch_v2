"""Define CLI flags and validation logic for documentation operations."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from docspatch.cache import DocsCache
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
    """Check configuration for conflicting operational flags.

    Raises:
        ConfigError: Mutually exclusive flags are active.
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
    """Select the appropriate remarks based on run status and user input.

    Returns:
        The resolved remarks string.
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


def preview_check(files: list[Path], repo_root: Path, cache: DocsCache, provider: str, tier: str) -> bool:
    """Display a preview of the documentation generation plan.

    Returns:
        True if documentation is required for any target.
    """
    # Deferred: planner pulls libcst via the source module — keep `flags` light
    # so importing it for RunFlags/validation never pays that cost.
    from docspatch.pipelines.docs.planner import Target, collect_targets

    found = collect_targets(files, repo_root, cache=cache).targets
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
