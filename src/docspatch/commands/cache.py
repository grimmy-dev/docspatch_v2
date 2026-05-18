"""dp cache subcommands."""

from pathlib import Path

from docspatch.context_store import CacheInfo, ContextStore
from docspatch.ui import console, kv_panel


def run_info() -> None:
    store = ContextStore(repo_root=Path.cwd())
    info: CacheInfo = store.get_cache_info()

    if info.file_count == 0:
        console.print("[dim]Cache is empty.[/dim]")
        return

    last = info.last_build.strftime("%Y-%m-%d %H:%M") if info.last_build else "—"
    console.print(
        kv_panel(
            "Scout cache",
            [
                ("Files", str(info.file_count)),
                ("Size", f"{info.total_size_bytes:,} bytes"),
                ("Last build", last),
            ],
        )
    )
