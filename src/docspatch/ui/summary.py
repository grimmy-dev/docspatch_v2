"""Functions to print execution metrics, cache hit ratios, and API costs to the terminal console."""

from collections.abc import Iterable

from docspatch.llm import TokenUsage
from docspatch.llm.pricing import actual_cost
from docspatch.ui.console import console
from docspatch.ui.panels import kv_panel


def cost_rows(usage: TokenUsage, provider: str, tier: str, *, sunk: bool = False) -> list[tuple[str, str]]:
    """Calculate LLM usage costs to generate structured metric rows for summary panels.

    Args:
        usage: Total tokens consumed during the run.
        provider: Name of the LLM provider.
        tier: Selected model tier determining the rates.
        sunk: Mark token costs as sunk when an execution is aborted.

    Returns:
        A list of label and value string pairs displaying token consumption and financial cost.
    """
    cost = actual_cost(provider, tier, usage.input_tokens, usage.output_tokens)
    label = "Tokens (sunk cost)" if sunk else "Tokens in / out"
    return [
        (label, f"{usage.input_tokens:,} / {usage.output_tokens:,}"),
        ("Cost", f"${cost.total:.4f}"),
    ]


def cache_hit_row(hits: int, total: int) -> tuple[str, str]:
    """Format cache hit statistics into a key-value row for the console summary.

    Args:
        hits: Number of cache-restored generation requests.
        total: Total number of generation requests executed.

    Returns:
        A key-value pair of strings detailing cache hits and ratio.
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
    """Print a structured key-value summary panel along with outstanding unresolved paths.

    Args:
        title: Header label for the summary panel.
        rows: List of key-value data rows to render.
        unresolved: File paths that were left without final decisions.
        border_style: Styling theme applied to the outer panel boundaries.
    """
    console.print(kv_panel(title, rows, border_style=border_style))
    pending = sorted(unresolved)
    if pending:
        console.print(f"[yellow]Unresolved ({len(pending)}):[/yellow]")
        for path in pending:
            console.print(f"  [dim]•[/dim] {path}")
