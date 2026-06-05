"""Compiles and executes LangGraph steps to scan codebases, parse surfaces, and extract implementation details."""

import asyncio
from collections.abc import Callable
from typing import Any

from langgraph.graph import END, START, StateGraph

from docspatch.llm import LLMClient
from docspatch.pipelines.readme.prompts import build_drill_prompt, build_triage_prompt, render_surfaces
from docspatch.pipelines.readme.state import DrillPlan, ReadmeState, Surface, TriageSelection
from docspatch.pipelines.readme.tools import get_file_surface, get_function_body
from docspatch.pipelines.readme.weaver import body_key, weave
from docspatch.source import estimate_tokens
from docspatch.utils.logging import get_logger

log = get_logger("readme.graph")

MAX_RETRIES = 2
"""Bad-plan retries before the subgraph proceeds with partial results."""


def build_readme_graph(
    repo_root: Any,  # noqa: ANN401 — a Path
    analysis_client: LLMClient,
    progress: Callable[[str], None] | None = None,
) -> Any:  # noqa: ANN401 — compiled langgraph is not nameable
    """Build the context-resolution state graph bound to a repository and analysis model.

    Args:
        repo_root: The local folder path of the repository.
        analysis_client: The fast-tier client driving triage and drill.
        progress: An optional callback reporting structural checkpoint messages.

    Returns:
        The compiled, in-memory graph.
    """
    triage_chain = analysis_client.with_structured_output(TriageSelection)
    drill_chain = analysis_client.with_structured_output(DrillPlan)

    def step(message: str) -> None:
        if progress is not None:
            progress(message)

    async def triage(state: ReadmeState) -> dict[str, Any]:
        step("Scanning the codebase for relevant files…")
        pre = state["pre_context"]
        prompt = build_triage_prompt(pre)
        selection, usage = await triage_chain.ainvoke(prompt)
        paths = [p for p in selection.paths if (repo_root / p).is_file()]
        log.debug("triage: %d/%d path(s) kept, ~%d tok in", len(paths), len(selection.paths), estimate_tokens(prompt))
        return {"selected_paths": paths, "usage": state["usage"] + usage, "phase": "drill"}

    async def surfaces(state: ReadmeState) -> dict[str, Any]:
        paths = state["selected_paths"]
        step(f"Reading {len(paths)} file surface(s)…")
        results = await asyncio.gather(*(asyncio.to_thread(get_file_surface, repo_root, p) for p in paths))
        surfaced = {p: s for p, s in zip(paths, results, strict=True) if s is not None}
        log.debug("surfaces: %d of %d path(s) parsed", len(surfaced), len(paths))
        return {"surfaces": surfaced}

    async def drill(state: ReadmeState) -> dict[str, Any]:
        step("Planning which implementations to read…")
        pre = state["pre_context"]
        prompt = build_drill_prompt(pre, render_surfaces(list(state["surfaces"].values())), state["drill_error"])
        plan, usage = await drill_chain.ainvoke(prompt)
        requests = [(b.path, b.function_name) for b in plan.bodies]
        log.debug("drill: %d body request(s), synthesis %d chars", len(requests), len(plan.synthesis))
        return {"synthesis": plan.synthesis, "body_requests": requests, "usage": state["usage"] + usage}

    async def bodies(state: ReadmeState) -> dict[str, Any]:
        surfaced = state["surfaces"]
        requests = state["body_requests"]
        bad = [(p, f) for p, f in requests if not _in_surface(surfaced, p, f)]
        if bad and state["retry_count"] < MAX_RETRIES:
            err = ", ".join(f"{p}::{f}" for p, f in bad)
            log.debug("bad plan, retry %d: %s", state["retry_count"] + 1, err)
            return {"phase": "drill", "retry_count": state["retry_count"] + 1, "drill_error": f"not in the surfaces: {err}"}
        good = [(p, f) for p, f in requests if _in_surface(surfaced, p, f)]
        if good:
            step(f"Reading {len(good)} key implementation(s)…")
        fetched = await asyncio.gather(*(asyncio.to_thread(get_function_body, repo_root, p, f) for p, f in good))
        body_map = {body_key(p, f): body for (p, f), body in zip(good, fetched, strict=True) if body is not None}
        log.debug("bodies: %d fetched of %d valid request(s)", len(body_map), len(good))
        return {"bodies": body_map, "phase": "done" if not bad else "exhausted"}

    def weave_node(state: ReadmeState) -> dict[str, Any]:
        step("Assembling the context…")
        woven = weave(state["pre_context"], state["synthesis"], state["surfaces"], state["bodies"])
        log.debug("weave: ~%d tok of context", estimate_tokens(woven))
        return {"woven": woven}

    graph: StateGraph = StateGraph(ReadmeState)
    graph.add_node("triage", triage)
    graph.add_node("surfaces", surfaces)
    graph.add_node("drill", drill)
    graph.add_node("bodies", bodies)
    graph.add_node("weave", weave_node)
    graph.add_edge(START, "triage")
    graph.add_edge("triage", "surfaces")
    graph.add_edge("surfaces", "drill")
    graph.add_edge("drill", "bodies")
    graph.add_conditional_edges("bodies", _route_after_bodies, {"drill": "drill", "weave": "weave"})
    graph.add_edge("weave", END)
    return graph.compile()


def _route_after_bodies(state: ReadmeState) -> str:
    """Determine the next execution node based on whether code body extraction requires retries.

    Args:
        state: The current execution state tracking retries and phase markers.

    Returns:
        The identifier of the next graph node to invoke.
    """
    return "drill" if state["phase"] == "drill" else "weave"


def _in_surface(surfaces: dict[str, Surface], path: str, function_name: str) -> bool:
    """Evaluate whether a function name is declared within parsed module surfaces.

    Args:
        surfaces: The parsed structure dictionary of repository files.
        path: The target module file path.
        function_name: The target function to seek within the module.

    Returns:
        True if the function is found in the specified parsed file surface.
    """
    surface = surfaces.get(path)
    return surface is not None and any(e.name == function_name for e in surface.entries)
