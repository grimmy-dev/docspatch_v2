"""Shared end-of-run summary panel for the docs and scout pipelines.

Each pipeline assembles its own rows and title; this module owns the panel
layout, the real-token cost rows, the cache-hit row, and the unresolved list.
"""

from collections.abc import Iterable

from docspatch.llm import TokenUsage
from docspatch.ui.console import console
from docspatch.ui.panels import kv_panel
from docspatch.utils.pricing import actual_cost


def cost_rows(usage: TokenUsage, provider: str, tier: str, *, sunk: bool = False) -> list[tuple[str, str]]:
    """Real-token rows for the summary panel.

    ``sunk`` flags an aborted run, where the tokens were billed but produced no
    written docstring — the label says so.
    """
    cost = actual_cost(provider, tier, usage.input_tokens, usage.output_tokens)
    label = "Tokens (sunk cost)" if sunk else "Tokens in / out"
    return [
        (label, f"{usage.input_tokens:,} / {usage.output_tokens:,}"),
        ("Cost", f"${cost.total:.4f}"),
    ]


def cache_hit_row(hits: int, total: int) -> tuple[str, str]:
    """Cache-hit ratio row — ``hits`` of ``total`` functions skipped via cache."""
    pct = f" ({hits * 100 // total}%)" if total else ""
    return ("Cache hits", f"{hits}/{total}{pct}")


def render_summary(
    title: str,
    rows: list[tuple[str, str]],
    *,
    unresolved: Iterable[str] = (),
    border_style: str = "green",
) -> None:
    """Print the summary panel, followed by the unresolved file list when non-empty."""
    console.print(kv_panel(title, rows, border_style=border_style))
    pending = sorted(unresolved)
    if pending:
        console.print(f"[yellow]Unresolved ({len(pending)}):[/yellow]")
        for path in pending:
            console.print(f"  [dim]•[/dim] {path}")
