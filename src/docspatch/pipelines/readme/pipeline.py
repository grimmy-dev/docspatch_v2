"""README pipeline: freshness gate, agent context resolution, generation, review."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from docspatch.llm import TokenUsage
from docspatch.manifest import ChangeManifest, ChangeSet, semantic_hash
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
    """Hash the scoped Python files and diff them against the README baseline.

    A file whose size and mtime match the stored stamp reuses its baseline hash,
    so only changed files pay the libcst compression cost. The first run hashes
    everything; later runs skip the unchanged majority.

    Args:
        repo_root: The repository root.
        scope: The repo-relative directory the README covers.

    Returns:
        The scoped paths, their semantic hashes and stamps, and the change set.

    Raises:
        PathError: The scope holds no Python files (fail fast).
    """
    root = repo_root.resolve()
    arg = Path("." if scope in _ROOT_SCOPES else scope)
    found = discover_targets([arg], root, ignore=load_docsignore(root))
    paths = sorted(p.relative_to(root).as_posix() for p in found)

    manifest = ChangeManifest(root)
    prev_hashes = manifest.baseline(MANIFEST_PIPELINE) or {}
    prev_stamps = manifest.stamps(MANIFEST_PIPELINE)
    hashes: dict[str, str] = {}
    stamps: dict[str, tuple[int, int]] = {}
    for p in paths:
        st = (root / p).stat()
        stamp = (st.st_size, st.st_mtime_ns)
        cached = prev_hashes.get(p)
        hashes[p] = cached if cached is not None and prev_stamps.get(p) == stamp else semantic_hash((root / p).read_text(encoding="utf-8"))
        stamps[p] = stamp

    return ScopeState(paths=paths, hashes=hashes, stamps=stamps, change_set=manifest.diff(MANIFEST_PIPELINE, hashes))


def is_fresh(scope: ScopeState, out_path: Path) -> bool:
    """Report whether the README is present and nothing scoped changed.

    Args:
        scope: The scoped hashes and change set.
        out_path: The README path.

    Returns:
        True when the README exists and the change set is empty.
    """
    return out_path.exists() and scope.change_set.empty


def build_pre_context(repo_root: Path, scope: str, state: ScopeState) -> PreContext:
    """Build the backbone the analysis passes travel with.

    Project facts, dependencies, and entry points apply at root scope only; a
    subpackage README stays at its own altitude.

    Args:
        repo_root: The repository root.
        scope: The repo-relative directory the README covers.
        state: The scoped paths and change set, for the tagged tree.

    Returns:
        The assembled backbone.
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
    """Render the scoped files as a change-tagged path list, removed paths included.

    Args:
        repo_root: The repository root.
        scope: The repo-relative directory the README covers.
        state: The scoped paths and change set.

    Returns:
        One repo-relative path per line, each tagged ``[new]``/``[updated]``/``[removed]``.
    """
    tag = {**dict.fromkeys(state.change_set.added, "[new]"), **dict.fromkeys(state.change_set.updated, "[updated]")}
    is_root = scope in _ROOT_SCOPES
    header = get_dir_tree(repo_root if is_root else repo_root / scope)
    lines = [f"{p} {tag[p]}".rstrip() if p in tag else p for p in state.paths]
    lines += [f"{p} [removed]" for p in state.change_set.removed]
    return f"{header}\n\nFiles:\n" + "\n".join(lines)


def _initial_state(pre: PreContext, existing: str | None) -> ReadmeState:
    """Seed graph state for a run.

    Returns:
        The starting state with empty model and context channels.
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
    """Resolve context with the agent graph, draft the README, review, and write on accept.

    Args:
        repo_root: The repository root.
        scope: The repo-relative directory the README covers.
        out_path: Destination README path.
        analysis_client: Fast-tier client driving triage and drill.
        generator: The README generator.
        prompter: Interface for user input.
        remarks: Optional run-wide instruction folded into every draft.
        provider: LLM provider, for the cost panel.
        tier: Generator tier, for the cost panel.

    Returns:
        The run outcome, including whether the file was written.
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

    with console.status("Reading the codebase…", spinner="dots") as live:
        graph = build_readme_graph(root, analysis_client, progress=lambda m: live.update(f"[cyan]{m}[/cyan]"))
        resolved = await graph.ainvoke(_initial_state(pre, existing))
    woven, ctx_usage = resolved["woven"], resolved["usage"]

    async def regenerate(feedback: tuple[str, ...]) -> tuple[str, TokenUsage]:
        return await generator.generate(pre=pre, woven=woven, existing_readme=existing, feedback=_fold(remarks, feedback))

    result = await review_readme(prompter, regenerate, existing=existing)
    usage = ctx_usage + result.usage

    written = result.accepted and result.markdown is not None
    if result.accepted and result.markdown is not None:
        atomic_write(out_path, result.markdown.rstrip("\n") + "\n")
        ChangeManifest(root).commit(MANIFEST_PIPELINE, state.hashes, state.stamps)
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
    """Combine the run-wide remark and accumulated revise notes into one block.

    Args:
        remarks: Optional run-wide instruction.
        feedback: Accumulated revise notes, oldest first.

    Returns:
        The joined instruction block, or null when there is nothing to add.
    """
    parts = ([remarks] if remarks else []) + [f"- {note}" for note in feedback]
    return "\n".join(parts) if parts else None
