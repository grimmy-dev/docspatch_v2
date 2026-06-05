"""Scans repository files, builds code context, prompts for review, and writes the updated README."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from docspatch.llm import TokenUsage
from docspatch.manifest import ChangeManifest, ChangeSet
from docspatch.pipelines.readme.generator import ReadmeGenerator
from docspatch.pipelines.readme.prompts import TOOL_DEFS
from docspatch.pipelines.readme.state import PreContext, ReadmeResult, ReadmeState
from docspatch.ui import Prompter, console, cost_rows, render_summary, status
from docspatch.ui.readme_review import review_readme
from docspatch.utils.fs import atomic_write
from docspatch.utils.ignore import load_docsignore
from docspatch.utils.logging import get_logger
from docspatch.utils.project import (
    entry_point_commands,
    entry_point_targets,
    get_dir_tree,
    project_dependencies,
    project_facts,
)
from docspatch.utils.scope import discover_targets

if TYPE_CHECKING:
    from docspatch.llm import LLMClient

log = get_logger("readme.pipeline")

MANIFEST_PIPELINE = "readme"
_ROOT_SCOPES = {".", "", "./"}


@dataclass(frozen=True)
class ScopeState:
    """The scoped files, their current hashes and stat stamps, and the change set."""

    paths: list[str]
    hashes: dict[str, str]
    stamps: dict[str, tuple[int, int]]
    change_set: ChangeSet


def scope_state(repo_root: Path, scope: str) -> ScopeState:
    """Hash scoped files and diff them against the manifest baseline to compute changes.

    Args:
        repo_root: The base directory of the repository.
        scope: The targeted subdirectory path within the repository.

    Returns:
        A ScopeState instance containing scanned paths, hashes, and changed sets.
    """
    root = repo_root.resolve()
    arg = Path("." if scope in _ROOT_SCOPES else scope)
    found = discover_targets([arg], root, ignore=load_docsignore(root))
    paths = sorted(p.relative_to(root).as_posix() for p in found)

    manifest = ChangeManifest(root)
    hashes, stamps = manifest.compute_state(MANIFEST_PIPELINE, root, paths)
    return ScopeState(paths=paths, hashes=hashes, stamps=stamps, change_set=manifest.diff(MANIFEST_PIPELINE, hashes))


def is_fresh(scope: ScopeState, out_path: Path) -> bool:
    """Check if the README file exists and matches the unmodified repository scope.

    Args:
        scope: The state of scoped file hashes and change history.
        out_path: The output file path of the README.

    Returns:
        True if the README exists and matches current file states.
    """
    return out_path.exists() and scope.change_set.empty


def build_pre_context(repo_root: Path, scope: str, state: ScopeState) -> PreContext:
    """Assemble project metadata, dependencies, and command entry points into a PreContext backbone.

    Args:
        repo_root: The root directory of the repository.
        scope: The relative folder scope of the README.
        state: The scanned file states and change manifests.

    Returns:
        The constructed pre-context metadata model.
    """
    is_root = scope in _ROOT_SCOPES
    return PreContext(
        scope=scope,
        tagged_tree=_tagged_tree(repo_root, scope, state),
        facts=project_facts(repo_root) if is_root else None,
        dependencies=tuple(project_dependencies(repo_root)) if is_root else (),
        entry_points=tuple(entry_point_commands(repo_root)) if is_root else (),
        entry_point_modules=frozenset(entry_point_targets(repo_root)),
        tool_defs=TOOL_DEFS,
    )


def _tagged_tree(repo_root: Path, scope: str, state: ScopeState) -> str:
    """Format scoped file listings as a directory tree tagged with modification markers.

    Args:
        repo_root: The directory root of the project.
        scope: The relative path scope of the README.
        state: The current file changes and tracked paths.

    Returns:
        A string listing directory trees with file-by-file annotations.
    """
    tag = {**dict.fromkeys(state.change_set.added, "[new]"), **dict.fromkeys(state.change_set.updated, "[updated]")}
    is_root = scope in _ROOT_SCOPES
    header = get_dir_tree(repo_root if is_root else repo_root / scope)
    lines = [f"{p} {tag[p]}".rstrip() if p in tag else p for p in state.paths]
    lines += [f"{p} [removed]" for p in state.change_set.removed]
    return f"{header}\n\nFiles:\n" + "\n".join(lines)


def _initial_state(pre: PreContext, existing: str | None) -> ReadmeState:
    """Build the starting state model for the context-resolution graph.

    Args:
        pre: The pre-context information block.
        existing: The content of the existing README if present.

    Returns:
        The initial ReadmeState mapping dictionary.
    """
    return {
        "phase": "triage",
        "retry_count": 0,
        "revision_count": 0,
        "feedback": None,
        "selected_paths": [],
        "synthesis": None,
        "body_requests": [],
        "drill_error": None,
        "pre_context": pre,
        "surfaces": {},
        "bodies": {},
        "woven": None,
        "existing_readme": existing,
        "markdown": None,
        "usage": TokenUsage(),
    }


async def generate_readme(
    repo_root: Path,
    scope: str,
    out_path: Path,
    *,
    analysis_client: LLMClient,
    generator: ReadmeGenerator,
    prompter: Prompter,
    remarks: str | None,
    provider: str,
    tier: str,
) -> ReadmeResult:
    """Generate the codebase context, draft the README, and prompt the user to approve changes.

    Args:
        repo_root: The root directory of the local repository.
        scope: The directory scope to analyze and write for.
        out_path: The destination file path for the README.
        analysis_client: The fast-tier model client.
        generator: The README builder client.
        prompter: The interaction terminal prompt receiver.
        remarks: Additional contextual instructions from the user.
        provider: The name of the LLM provider.
        tier: The generator model speed/size tier.

    Returns:
        The pipeline outcome showing write status and token use.
    """
    from docspatch.pipelines.readme.graph import build_readme_graph

    root = repo_root.resolve()
    with status("Checking for changes…"):
        state = scope_state(root, scope)
    existing = out_path.read_text() if out_path.exists() else None

    if is_fresh(state, out_path):
        console.print("[green]✓[/green] README is fresh — nothing scoped changed.")
        return ReadmeResult(written=False, out_path=None, usage=TokenUsage())

    pre = build_pre_context(root, scope, state)
    log.debug("pre-context: %d scoped file(s), %d changed", len(state.paths), len(state.change_set.changed))

    log.debug("resolving context for %d scoped file(s)", len(state.paths))
    with console.status("Reading the codebase…", spinner="dots") as live:
        graph = build_readme_graph(root, analysis_client, progress=lambda m: live.update(f"[cyan]{m}[/cyan]"))
        resolved = await graph.ainvoke(_initial_state(pre, existing))
    woven, ctx_usage = resolved["woven"], resolved["usage"]
    log.debug("context resolved: %d surface(s), %d body(ies)", len(resolved.get("surfaces", {})), len(resolved.get("bodies", {})))

    async def regenerate(feedback: tuple[str, ...]) -> tuple[str, TokenUsage]:
        return await generator.generate(pre=pre, woven=woven, existing_readme=existing, feedback=_fold(remarks, feedback))

    result = await review_readme(prompter, regenerate, existing=existing)
    usage = ctx_usage + result.usage

    written = result.accepted and result.markdown is not None
    if result.accepted and result.markdown is not None:
        atomic_write(out_path, result.markdown.rstrip("\n") + "\n")
        ChangeManifest(root).commit(MANIFEST_PIPELINE, state.hashes, state.stamps)
        log.debug("recorded readme manifest: %d path(s)", len(state.hashes))
        console.print(f"[green]✓[/green] Wrote {out_path}")
    else:
        console.print("[dim]README discarded — nothing written.[/dim]")

    render_summary(
        "README written" if written else "README cancelled",
        cost_rows(usage, provider, tier),
        border_style="green" if written else "yellow",
    )
    return ReadmeResult(written=written, out_path=out_path if written else None, usage=usage)


def _fold(remarks: str | None, feedback: tuple[str, ...]) -> str | None:
    """Combine starting instructions and iterative review suggestions into a single feedback block.

    Args:
        remarks: Top-level instructions provided at CLI invocation.
        feedback: A sequence of review remarks collected during evaluation.

    Returns:
        The combined feedback string, or null if empty.
    """
    parts = ([remarks] if remarks else []) + [f"- {note}" for note in feedback]
    return "\n".join(parts) if parts else None
