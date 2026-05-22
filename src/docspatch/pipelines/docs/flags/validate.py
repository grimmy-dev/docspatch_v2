"""Mutex validation for ``dp docs`` run flags."""

from __future__ import annotations

from docspatch.pipelines.docs.flags.models import RunFlags
from docspatch.utils.errors import ConfigError

# Flag pairs that cannot be combined, with the hint shown on conflict.
_CONFLICTS = (
    ("check", "update", "Preview with --check, then run without it to write."),
    ("check", "remarks", "--remarks affects generation; --check generates nothing."),
    ("check", "resume", "--check starts a fresh preview; it cannot resume a run."),
    ("update", "resume", "A resumed run keeps its scope; --update cannot widen it."),
    ("resume", "path", "A resumed run reuses its original scope — drop the paths."),
)


def validate_run_flags(flags: RunFlags) -> None:
    """Reject conflicting flag combinations with an actionable error."""
    active = {
        "check": flags.check,
        "update": flags.update,
        "remarks": flags.remarks is not None,
        "resume": flags.resume,
        "path": bool(flags.paths),
    }
    for a, b, hint in _CONFLICTS:
        if active[a] and active[b]:
            raise ConfigError(f"--{a} and --{b} cannot be used together.", hint=hint)
