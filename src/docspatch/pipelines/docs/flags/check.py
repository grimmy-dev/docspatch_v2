"""``--check`` preview: list undocumented functions per file without writing."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from docspatch.cache import DocsCache
from docspatch.llm import tier_info
from docspatch.pipelines.docs.planner import Target, collect_targets
from docspatch.ui import build_table, console
from docspatch.utils.pricing import estimate_cost


def preview_check(
    files: list[Path], repo_root: Path, cache: DocsCache, provider: str, tier: str
) -> bool:
    """Render the ``--check`` preview. Returns True when any function needs docs.

    Writes nothing — the caller maps the result to an exit code so the command
    works as a pre-commit or post-commit hook.
    """
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
        est = estimate_cost(provider, tier, sum(t.token_cost for t in items), output_ratio=0.6)
        rows.append([rel, str(len(items)), f"~{est.input_tokens:,}", f"${est.total:.4f}"])
        total_fns += len(items)
        total_tokens += est.input_tokens
        total_cost += est.total
    rows.append(["TOTAL", str(total_fns), f"~{total_tokens:,}", f"${total_cost:.4f}"])

    console.print(f"[bold]{tier_info(provider, tier).model}[/bold] · {tier} tier")
    console.print(build_table(["FILE", "UNDOCUMENTED", "INPUT TOKENS", "COST"], rows))
    console.print(
        f"[yellow]{total_fns} function(s) across {len(by_file)} file(s) need docstrings.[/yellow]"
    )
    console.print("[dim]Run [/dim]dp docs[dim] to document them.[/dim]")
    return True
