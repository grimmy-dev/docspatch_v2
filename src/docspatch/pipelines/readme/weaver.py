"""Assemble the generator context from code artifacts: backbone, synthesis, tiered surfaces, bodies."""

from dataclasses import replace

from docspatch.pipelines.readme.prompts import render_backbone, render_surface
from docspatch.pipelines.readme.state import PreContext, Surface
from docspatch.utils.project import is_entry_point_path


def body_key(path: str, function_name: str) -> str:
    """Build the dict key under which a drilled body is stored.

    Args:
        path: Repo-relative source path.
        function_name: The drilled function or method name.

    Returns:
        The ``path::function`` key.
    """
    return f"{path}::{function_name}"


def relevance_tier(path: str, entry_point_modules: frozenset[str]) -> int:
    """Rank a path for surface ordering: entry points, then pipelines, then the rest.

    Args:
        path: Repo-relative source path.
        entry_point_modules: Declared entry-point modules.

    Returns:
        0 for an entry-point file, 1 for pipeline internals, 2 otherwise.
    """
    if is_entry_point_path(path, set(entry_point_modules)):
        return 0
    if path.startswith("pipelines/") or "/pipelines/" in path:
        return 1
    return 2


def weave(pre: PreContext, synthesis: str | None, surfaces: dict[str, Surface], bodies: dict[str, str]) -> str:
    """Assemble the generator context, entry-point surfaces first, drilled bodies in full.

    A drilled body supersedes its function's surface stub: the stub is dropped
    and the full body printed; other functions on the same file keep their stubs.

    Args:
        pre: The run backbone.
        synthesis: The drill orientation paragraph, or null.
        surfaces: Tool 2 results keyed by path.
        bodies: Tool 3 results keyed by ``path::function``.

    Returns:
        The woven context string fed to the generator.
    """
    parts = [render_backbone(pre)]
    if synthesis:
        parts.append(
            "Shared understanding of the project (write the README from this — it captures the "
            f"intent, the main flow, and what makes the project worth using):\n{synthesis}\n"
        )
    ordered = sorted(surfaces.values(), key=lambda s: (relevance_tier(s.path, pre.entry_point_modules), s.path))
    rendered = [render_surface(_without_drilled(s, bodies)) for s in ordered]
    if rendered:
        parts.append("Public surfaces:\n" + "\n\n".join(rendered) + "\n")
    if bodies:
        blocks = [f"#### {key}\n{body}" for key, body in bodies.items()]
        parts.append("Key implementations:\n" + "\n\n".join(blocks) + "\n")
    return "\n".join(parts)


def _without_drilled(surface: Surface, bodies: dict[str, str]) -> Surface:
    """Drop the surface stubs whose full body was drilled for this file.

    Returns:
        The surface with drilled entries removed; unchanged when none were drilled.
    """
    kept = [e for e in surface.entries if body_key(surface.path, e.name) not in bodies]
    if len(kept) == len(surface.entries):
        return surface
    return replace(surface, entries=kept)
