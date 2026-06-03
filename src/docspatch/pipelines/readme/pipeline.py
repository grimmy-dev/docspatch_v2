"""Main pipeline for scoping, generating, and reviewing README updates."""

from dataclasses import replace
from pathlib import Path

from docspatch.cache import ScoutCache
from docspatch.pipelines.readme.generator import ReadmeGenerator
from docspatch.pipelines.readme.markers import select, under_scope
from docspatch.pipelines.readme.prompts import ReadmeContext
from docspatch.pipelines.readme.state import ReadmeResult
from docspatch.pipelines.scout.overview import read_overview
from docspatch.pipelines.scout.pipeline import execute, tracked_paths
from docspatch.pipelines.scout.planner import plan_uncached
from docspatch.pipelines.scout.unified import UNIFIED_NAME, write_unified
from docspatch.ui import Prompter, console, cost_rows, render_summary, status
from docspatch.ui.readme_review import review_readme
from docspatch.utils.config import ConfigStore
from docspatch.utils.errors import ReadmeError
from docspatch.utils.fs import atomic_write
from docspatch.utils.logging import get_logger
from docspatch.utils.project import get_dir_tree, project_dependencies, project_facts

log = get_logger("readme.pipeline")

_ROOT_SCOPES = {".", "", "./"}


def ensure_scope_fresh(
    repo_root: Path,
    ctx_store: ScoutCache,
    store: ConfigStore,
    provider: str,
    api_key: str,
    scope: str,
    p: Prompter,
) -> None:
    """Re-scout in-scope files that changed, then rewrite the unified summary.

    Args:
        repo_root: The repository root.
        ctx_store: The scout cache.
        store: The configuration store.
        provider: The LLM provider for any re-scout calls.
        api_key: Provider credentials.
        scope: The repo-relative directory the README covers.
        p: Interface for user input.
    """
    with status("Checking context…"):
        tracked = tracked_paths(repo_root)
        in_scope = [path for path in tracked if under_scope(path, scope)]
        scan = plan_uncached(in_scope, ctx_store)
    log.debug("refresh: %d in-scope file(s), %d changed", len(in_scope), len(scan.uncached))
    if scan.uncached:
        execute(ctx_store, store, provider, api_key, scan, p)
    with status("Refreshing summary…"):
        write_unified(ctx_store, tracked, repo_root, read_overview(repo_root))


def _build_context(repo_root: Path, scope: str, out_path: Path, remarks: str | None) -> ReadmeContext:
    """Resolve the facts, tree, and existing README a prompt draws on.

    Args:
        repo_root: The repository root.
        scope: The repo-relative directory the README covers.
        out_path: Where the README will be written (read for tone if present).
        remarks: Optional run-wide instruction.

    Returns:
        The assembled README context.
    """
    is_root = scope in _ROOT_SCOPES
    tree_root = repo_root if is_root else repo_root / scope
    existing = out_path.read_text() if out_path.exists() else None
    return ReadmeContext(
        scope=scope,
        dir_tree=get_dir_tree(tree_root),
        facts=project_facts(repo_root) if is_root else None,
        dependencies=tuple(project_dependencies(repo_root)) if is_root else (),
        existing_readme=existing,
        remarks=remarks,
    )


async def generate_readme(
    repo_root: Path,
    scope: str,
    out_path: Path,
    *,
    generator: ReadmeGenerator,
    prompter: Prompter,
    remarks: str | None,
    provider: str,
    tier: str,
) -> ReadmeResult:
    """Draft the README from scoped summaries, review it, and write on accept.

    Args:
        repo_root: The repository root.
        scope: The repo-relative directory the README covers.
        out_path: Destination README path.
        generator: The README generator.
        prompter: Interface for user input.
        remarks: Optional run-wide instruction.
        provider: LLM provider, for the cost panel.
        tier: Generator tier, for the cost panel.

    Returns:
        The run outcome, including whether the file was written.

    Raises:
        ReadmeError: No scoped summaries are available to draw on.
    """
    summary_path = repo_root / ".docspatch" / UNIFIED_NAME
    if not summary_path.exists():
        raise ReadmeError.no_summaries(scope)
    doc = select(summary_path.read_text(), scope)
    if not doc.files:
        raise ReadmeError.no_summaries(scope)
    log.debug("scoped summary: %d block(s) under %s", len(doc.files), scope)

    ctx = _build_context(repo_root, scope, out_path, remarks)

    async def regenerate(feedback: tuple[str, ...]):
        return await generator.generate(replace(ctx, feedback=feedback), doc.files)

    result = await review_readme(prompter, regenerate)
    if result.accepted and result.markdown is not None:
        atomic_write(out_path, result.markdown.rstrip("\n") + "\n")
        console.print(f"[green]✓[/green] Wrote {out_path}")
    else:
        console.print("[dim]README discarded — nothing written.[/dim]")

    written = result.accepted and result.markdown is not None
    render_summary(
        "README written" if written else "README cancelled",
        cost_rows(result.usage, provider, tier),
        border_style="green" if written else "yellow",
    )
    return ReadmeResult(written=written, out_path=out_path if written else None, usage=result.usage)
