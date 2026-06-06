"""Interleaves directory trees, file surfaces, and compressed function bodies into a consolidated prompt context."""

from dataclasses import replace

from docspatch.pipelines.readme.prompts import render_backbone, render_surface
from docspatch.pipelines.readme.state import PreContext, Surface
from docspatch.utils.entry_points import is_entry_point_path


def body_key(path: str, function_name: str) -> str:
    """Compute a unique string identifier mapping a function to its source file.

    Args:
        path: The repo-relative path of the file.
        function_name: The name of the target function.

    Returns:
        A formatted identifier string.
    """
    return f"{path}::{function_name}"


def relevance_tier(path: str, entry_point_modules: frozenset[str]) -> int:
    """Assign a sorting priority to a file path based on its project role.

    Args:
        path: The repo-relative source path.
        entry_point_modules: A set of entry point modules.

    Returns:
        An integer rank defining priority.
    """
    if is_entry_point_path(path, set(entry_point_modules)):
        return 0
    if path.startswith("pipelines/") or "/pipelines/" in path:
        return 1
    return 2


def weave(pre: PreContext, synthesis: str | None, surfaces: dict[str, Surface], bodies: dict[str, str]) -> str:
    """Blend project synthesis, public surfaces, and drilled source bodies into a single coherent prompt string.

    Args:
        pre: The baseline pipeline context.
        synthesis: The project summary orientation text.
        surfaces: A map of file paths to extracted public surfaces.
        bodies: A map of body keys to compressed implementations.

    Returns:
        The fully synthesized context ready for prompting.
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
    """Filter out public surface stubs for functions whose implementations have already been extracted in full.

    Args:
        surface: The public surface definitions of a file.
        bodies: The collection of fully extracted implementations.

    Returns:
        A modified surface object with overlapping stubs removed.
    """
    kept = [e for e in surface.entries if body_key(surface.path, e.name) not in bodies]
    if len(kept) == len(surface.entries):
        return surface
    return replace(surface, entries=kept)
