"""dp cache subcommands."""

from pathlib import Path

from rich.table import Table

from docspatch.context_store import CacheInfo, ContextStore
from docspatch.ui.console import console


def run_info() -> None:
    store = ContextStore(repo_root=Path.cwd())
    info: CacheInfo = store.get_cache_info()

    if info.file_count == 0:
        console.print("[dim]Cache is empty.[/dim]")
        return

    last = info.last_build.strftime("%Y-%m-%d %H:%M") if info.last_build else "—"
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_row("[bold]Files[/bold]", str(info.file_count))
    table.add_row("[bold]Size[/bold]", f"{info.total_size_bytes:,} bytes")
    table.add_row("[bold]Last build[/bold]", last)
    console.print(table)
