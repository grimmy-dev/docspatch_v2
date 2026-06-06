"""Plan-time lookup of heavy target bodies and file hashes, kept out of graph state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from docspatch.pipelines.docs.planner import Target
from docspatch.pipelines.docs.state import GenKey, TargetRef
from docspatch.source import file_hash


@dataclass(frozen=True)
class TargetRegistry:
    """Per-run lookup built once at plan time.

    Holds the heavy source bodies and the plan-time file hashes so neither
    travels through the serialized graph state. The plan node builds it; batch
    sizing, generation, rerun, and the commit conflict check read it.
    """

    targets: dict[GenKey, Target]
    plan_hashes: dict[str, str]

    @classmethod
    def from_targets(cls, root: Path, targets: list[Target]) -> TargetRegistry:
        """Build the registry from planned targets, snapshotting each file's hash.

        The hash captured here lets the commit step detect a file that changed
        on disk between planning and writing.

        Args:
            root: Resolved repository root.
            targets: Targets discovered by the planner.

        Returns:
            A registry mapping target keys to bodies and files to plan-time hashes.
        """
        by_key = {(t.rel, t.qualname): t for t in targets}
        hashes = {rel: file_hash((root / rel).read_text()) for rel in {t.rel for t in targets}}
        return cls(targets=by_key, plan_hashes=hashes)

    def token_cost(self, ref: TargetRef) -> int:
        """Return the planned token cost of one target.

        Args:
            ref: Reference to the target.

        Returns:
            The target's estimated token cost.
        """
        return self.targets[(ref.rel, ref.qualname)].token_cost

    def get(self, ref: TargetRef) -> Target | None:
        """Return the full target for a ref, or None if it is out of scope.

        Args:
            ref: Reference to the target.

        Returns:
            The target with its source body, or None.
        """
        return self.targets.get((ref.rel, ref.qualname))

    def __contains__(self, ref: TargetRef) -> bool:
        """Return whether a target ref is in scope this run."""
        return (ref.rel, ref.qualname) in self.targets

    def plan_hash(self, rel: str) -> str | None:
        """Return the file's hash captured at plan time, or None.

        Args:
            rel: The file's repo-relative path.

        Returns:
            The plan-time hash, or None when the file had no targets.
        """
        return self.plan_hashes.get(rel)
