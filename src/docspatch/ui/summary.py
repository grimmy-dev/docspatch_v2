"""Display session metrics and cost information."""

from collections.abc import Iterable

from docspatch.llm import TokenUsage
from docspatch.llm.pricing import actual_cost
from docspatch.ui.console import console
from docspatch.ui.panels import kv_panel


def cost_rows(usage: TokenUsage, provider: str, tier: str, *, sunk: bool = False) -> list[tuple[str, str]]:
    """Generate tabular rows for token usage and costs.

    Args:
        usage: Consumed tokens.
        sunk: Flag for aborted runs.

    Returns:
        List of string pairs.
    """
    cost = actual_cost(provider, tier, usage.input_tokens, usage.output_tokens)
    label = "Tokens (sunk cost)" if sunk else "Tokens in / out"
    return [
        (label, f"{usage.input_tokens:,} / {usage.output_tokens:,}"),
        ("Cost", f"${cost.total:.4f}"),
    ]


def cache_hit_row(hits: int, total: int) -> tuple[str, str]:
    """Generate a summary row for cache performance.

    Returns:
        Label and formatted ratio string.
    """
    pct = f" ({hits * 100 // total}%)" if total else ""
    return ("Cache hits", f"{hits}/{total}{pct}")


def render_summary(
    title: str,
    rows: list[tuple[str, str]],
    *,
    unresolved: Iterable[str] = (),
    border_style: str = "green",
) -> None:
    """Display the summary panel with unresolved items.

    Args:
        unresolved: Items left without decisions.
    """
    console.print(kv_panel(title, rows, border_style=border_style))
    pending = sorted(unresolved)
    if pending:
        console.print(f"[yellow]Unresolved ({len(pending)}):[/yellow]")
        for path in pending:
            console.print(f"  [dim]•[/dim] {path}")
