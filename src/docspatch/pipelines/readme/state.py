"""Graph state, code-built context, and structured-output schemas for the README pipeline."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TypedDict

from pydantic import BaseModel, Field

from docspatch.llm import TokenUsage
from docspatch.utils.project import ProjectFacts

# ---- code-built context ----------------------------------------------------


@dataclass(frozen=True)
class SurfaceEntry:
    """One public function or class: its signature and docstring, no body."""

    kind: Literal["function", "class"]
    name: str
    signature: str
    docstring: str | None = None


@dataclass(frozen=True)
class Surface:
    """A file's public surface — what Tool 2 returns for one selected path."""

    path: str
    module_doc: str | None
    entries: list[SurfaceEntry] = field(default_factory=list)


@dataclass(frozen=True)
class PreContext:
    """The backbone that travels with triage and drill: tree, facts, tool menu.

    The existing README is deliberately absent — it can be large and only the
    generator needs it.
    """

    scope: str
    tagged_tree: str
    facts: ProjectFacts | None
    dependencies: tuple[str, ...]
    entry_points: tuple[str, ...]
    entry_point_modules: frozenset[str]
    tool_defs: str


# ---- structured output -----------------------------------------------------


class TriageSelection(BaseModel):
    """Triage pass output: the files worth surfacing for this scope."""

    paths: list[str] = Field(default_factory=list, description="Repo-relative paths to surface, drawn from the directory tree.")


class BodyRequest(BaseModel):
    """A single drilled body: a function on a surfaced path."""

    path: str = Field(description="Repo-relative file path, exactly as it appears in the surfaces.")
    function_name: str = Field(description="Function or method name whose full body is needed.")


class DrillPlan(BaseModel):
    """Drill pass output: bodies to fetch plus a mandatory orientation synthesis."""

    bodies: list[BodyRequest] = Field(
        default_factory=list,
        description="Functions whose full body the README needs; empty when surfaces already suffice.",
    )
    synthesis: str = Field(
        description=(
            "4-6 sentences of confident, concrete prose that put the README author on the same page "
            "as the project: the problem it solves and who it's for, what the main entry points and "
            "commands do, how the major pieces fit and the data/control flow between them, and the "
            "design choice or behaviour that makes it distinctive and worth using. This is the "
            "shared understanding the README is written from — capture intent and spirit, not just "
            "a feature list."
        ),
    )


# ---- graph state -----------------------------------------------------------


class ReadmeState(TypedDict):
    """Everything the README graph reads and writes across nodes."""

    # control flags
    phase: Literal["triage", "drill", "done", "exhausted"]
    retry_count: int
    revision_count: int
    feedback: str | None
    # model-generated
    selected_paths: list[str]
    synthesis: str | None
    body_requests: list[tuple[str, str]]
    drill_error: str | None
    # code-built context
    pre_context: PreContext
    surfaces: dict[str, Surface]
    bodies: dict[str, str]
    woven: str | None
    # generation
    existing_readme: str | None
    markdown: str | None
    usage: TokenUsage


@dataclass(frozen=True)
class ReadmeResult:
    """Outcome of a README run.

    ``out_path`` is the written file when ``written`` is true, else null (the
    user cancelled). ``usage`` totals every generation call, revisions included.
    """

    written: bool
    out_path: Path | None
    usage: TokenUsage
