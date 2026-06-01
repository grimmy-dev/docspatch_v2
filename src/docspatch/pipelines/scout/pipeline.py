"""Orchestrate the pre-build scouting workflow. This module interacts with the user to manage scouting, caching, and cost estimation."""

import asyncio
from pathlib import Path

from docspatch.cache import ScoutCache
from docspatch.llm import LLMClient, TokenUsage
from docspatch.llm.catalogue import tier_info
from docspatch.llm.pricing import estimate_cost
from docspatch.pipelines.scout.graph import run_scout
from docspatch.pipelines.scout.planner import plan_uncached
from docspatch.pipelines.scout.state import ScanPlan, ScoutResult
from docspatch.pipelines.scout.unified import write_unified
from docspatch.schemas import RunSettings
from docspatch.ui import Prompter, console, cost_panel, cost_rows, progress_bar, render_summary, status
from docspatch.ui.retry_display import RetryDisplay
from docspatch.utils.config import ConfigStore
from docspatch.utils.errors import PathError
from docspatch.utils.ignore import load_docsignore
from docspatch.utils.scope import discover_targets
from docspatch.utils.switcher import offer_switch


def pre_build(
    repo_root: Path,
    ctx_store: ScoutCache,
    store: ConfigStore,
    provider: str,
    api_key: str,
    p: Prompter,
) -> None:
    """Trigger the scouting pipeline for tracked files.

    Args:
        repo_root: Directory containing the codebase.
        ctx_store: Scout cache for persistent state.
        store: Configuration manager.
    """
    paths = tracked_paths(repo_root)
    if not paths:
        return

    with status("Scanning tracked files for changes..."):
        scan = plan_uncached(paths, ctx_store)

    if scan.all_current:
        console.print("[dim]Context already up to date — skipping scout.[/dim]")
        write_unified(ctx_store, paths, repo_root)
        return

    print_estimate(provider, scan)

    if not p.confirm("Run scout pre-build now?"):
        console.print("[dim]Scout skipped.[/dim]")
        return

    execute(ctx_store, store, provider, api_key, scan, p)
    write_unified(ctx_store, paths, repo_root)


def tracked_paths(repo_root: Path) -> list[str]:
    """Gather project files while excluding ignored paths.

    Args:
        repo_root: Path to the repository.

    Returns:
        List of relative paths.
    """
    root = repo_root.resolve()
    try:
        found = discover_targets([Path(".")], root, ignore=load_docsignore(root))
    except PathError:
        return []
    return [p.relative_to(root).as_posix() for p in found]


def print_estimate(provider: str, scan: ScanPlan) -> None:
    """Display the projected cost panel for a scan operation.

    Args:
        provider: The name of the LLM provider.
        scan: The plan detailing files to be scouted.
    """
    fast_info = tier_info(provider, "fast")
    est = estimate_cost(provider, "fast", scan.token_estimate)
    console.print(
        cost_panel(
            "Scout pre-build estimate",
            [
                ("Model", fast_info.model),
                ("Tier", "fast"),
                ("Files (uncached)", f"{scan.uncached_count} of {scan.uncached_count + scan.cached_count}"),
                ("Input tokens", f"~{est.input_tokens:,}"),
                ("Output tokens", f"~{est.output_tokens:,} (projected)"),
                ("Cost", f"~${est.total:.4f}  (in ${est.input_cost:.4f} + out ${est.output_cost:.4f})"),
            ],
        )
    )


def execute(
    ctx_store: ScoutCache,
    store: ConfigStore,
    provider: str,
    api_key: str,
    scan: ScanPlan,
    p: Prompter,
) -> None:
    """Run the scout pipeline for identified targets and report the final outcome.

    Args:
        ctx_store: The cache storage for scout context.
        store: The global configuration storage.
        provider: The LLM provider for the operation.
        api_key: The authentication key for the provider.
        scan: The scan plan identifying files to process.
        p: The prompt manager.
    """
    retry_display = RetryDisplay()
    llm = LLMClient(provider=provider, api_key=api_key, generator_tier="fast", retry_cb=retry_display)
    targets = list(scan.uncached)

    async def handle_exhaustion(current: LLMClient) -> LLMClient | None:
        result = await offer_switch(
            store,
            p,
            current_provider=current.provider,
            current_model=current.generator_model,
            retry_cb=retry_display,
        )
        return result.client if result else None

    settings = RunSettings.from_config(store.read())
    with progress_bar(total=len(targets), description="Scouting") as bar:
        retry_display.bind(bar.set_status)
        try:
            result = asyncio.run(
                run_scout(
                    targets,
                    ctx_store,
                    llm,
                    progress_cb=lambda path_str: bar(Path(path_str).name),
                    switch_handler=handle_exhaustion,
                    batch_token_limit=settings.batch_token_limit,
                    concurrency_limit=settings.concurrency_limit,
                    call_timeout=settings.call_timeout,
                    precomputed_misses=list(scan.misses),
                )
            )
        finally:
            retry_display.unbind()

    report_scout(provider, result)


def report_scout(provider: str, result: ScoutResult) -> None:
    """Render the summary panel for the scouting process.

    Args:
        provider: The provider used for the scout.
        result: The outcome of the scouting process.
    """
    usage = TokenUsage(result.input_tokens, result.output_tokens)
    rows = [
        ("Model", f"{tier_info(provider, 'fast').model} ({provider})"),
        ("Files scouted", str(result.scouted)),
        ("Cached (skipped)", str(result.skipped)),
        *cost_rows(usage, provider, "fast"),
    ]
    render_summary("Scout pre-build complete", rows, unresolved=result.unresolved)
