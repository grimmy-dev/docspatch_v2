"""End-to-end scout pre-build: scan → estimate → confirm → execute.

Wraps :func:`scout_files` with the UX needed by ``dp init`` and any other
command that wants to refresh the cache up front: cost panel, confirmation
prompt, progress bar, retry countdown, exhaustion-driven provider switch.
"""

import asyncio
from pathlib import Path

from docspatch.context_store import ContextStore
from docspatch.llm import LLM_RETRY, LLMClient
from docspatch.llm.catalogue import tier_info
from docspatch.pipelines.scout.planner import plan_uncached
from docspatch.pipelines.scout.runner import scout_files
from docspatch.pipelines.scout.types import ScanPlan
from docspatch.ui import Prompter, console, kv_panel, progress_bar, status
from docspatch.utils.config import ConfigStore
from docspatch.utils.errors import GitError
from docspatch.utils.git_reader import GitReader
from docspatch.utils.pricing import estimate_cost
from docspatch.utils.switcher import offer_switch


def pre_build(
    repo_root: Path,
    ctx_store: ContextStore,
    store: ConfigStore,
    provider: str,
    api_key: str,
    p: Prompter,
) -> None:
    """Optionally refresh the scout cache for every tracked Python file.

    No-op when the repo has no tracked files, the cache is already current, or
    the user declines the confirmation.
    """
    paths = tracked_paths(repo_root)
    if not paths:
        return

    with status("Scanning tracked files for changes..."):
        scan = plan_uncached(paths, ctx_store)

    if scan.all_current:
        console.print("[dim]Context already up to date — skipping scout.[/dim]")
        return

    print_estimate(provider, scan)

    if not p.confirm("Run scout pre-build now?"):
        console.print("[dim]Scout skipped.[/dim]")
        return

    execute(ctx_store, store, provider, api_key, scan, p)


def tracked_paths(repo_root: Path) -> list[str]:
    """Return git-tracked Python files as repo-relative POSIX strings. Empty list on failure."""
    try:
        return GitReader(cwd=repo_root).list_tracked_files()
    except GitError:
        return []


def print_estimate(provider: str, scan: ScanPlan) -> None:
    """Render the projected cost panel for an uncached scan."""
    fast_info = tier_info(provider, "fast")
    est = estimate_cost(provider, "fast", scan.token_estimate)
    console.print(
        kv_panel(
            "Scout pre-build estimate",
            [
                ("Files (uncached)", f"{scan.uncached_count} of {scan.uncached_count + scan.cached_count}"),
                ("Input tokens", f"~{est.input_tokens:,}"),
                ("Output tokens", f"~{est.output_tokens:,} (projected)"),
                ("Model", fast_info.model),
                ("Cost", f"~${est.total:.4f}  (in ${est.input_cost:.4f} + out ${est.output_cost:.4f})"),
            ],
        )
    )


def execute(
    ctx_store: ContextStore,
    store: ConfigStore,
    provider: str,
    api_key: str,
    scan: ScanPlan,
    p: Prompter,
) -> None:
    """Run the scout pipeline against ``scan.uncached`` and render the summary."""
    llm = LLMClient(provider=provider, api_key=api_key, generator_tier="fast", retry_cb=retry_console)
    targets = list(scan.uncached)

    async def handle_exhaustion(current: LLMClient) -> LLMClient | None:
        result = await offer_switch(
            store,
            p,
            current_provider=current.provider,
            current_model=current.generator_model,
            retry_cb=retry_console,
        )
        return result.client if result else None

    with progress_bar(total=len(targets), description="Scouting") as advance:
        result = asyncio.run(
            scout_files(
                targets,
                ctx_store,
                llm,
                progress_cb=lambda path_str: advance(Path(path_str).name),
                switch_handler=handle_exhaustion,
            )
        )

    console.print(f"[green]✓[/green] Scout complete: {result.scouted} scouted, {result.skipped} cached")
    if result.unresolved:
        console.print(f"[yellow]⚠[/yellow] {len(result.unresolved)} file(s) could not be summarised. Re-run dp init to retry.")


def retry_console(attempt: int, sleep_s: float) -> None:
    """Render rate-limit countdown without coupling LLMClient to rich."""
    console.print(f"[yellow]Rate limited — retrying in {sleep_s:.0f}s ({attempt}/{LLM_RETRY.max_attempts - 1})[/yellow]")
