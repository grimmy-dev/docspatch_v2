"""RunFlags — the flags for one ``dp docs`` invocation. Plain data."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RunFlags:
    """Flags for one ``dp docs`` invocation, plumbed CLI -> command -> graph state."""

    paths: tuple[Path, ...] = ()
    check: bool = False
    update: bool = False
    remarks: str | None = None
    resume: bool = False
    no_ignore: bool = False
