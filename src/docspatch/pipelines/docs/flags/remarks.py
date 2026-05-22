"""``--remarks`` resolution: keep prior remarks across a resume, override on demand."""

from __future__ import annotations

from docspatch.ui import console, kv_panel
from docspatch.ui.prompter import Prompter


def resolve_remarks(
    *, is_resume: bool, prior: str | None, requested: str | None, prompter: Prompter | None
) -> str | None:
    """Return the remarks to use for this run.

    A fresh run uses ``requested``. A resumed run keeps ``prior`` unless a
    different ``--remarks`` was passed, which overrides after the user confirms
    (non-interactive runs take the new value without prompting).
    """
    if not is_resume:
        return requested
    if requested is None or requested == prior:
        return prior
    if prompter is None:
        return requested
    console.print(
        kv_panel(
            "Remarks changed for this resumed run",
            [("Original", prior or "(none)"), ("New", requested)],
            border_style="yellow",
        )
    )
    if prompter.confirm("Use the new remarks instead of the original?"):
        return requested
    return prior
