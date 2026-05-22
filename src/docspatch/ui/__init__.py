"""Reusable rich-based UI primitives.

Commands and pipeline nodes import from here only — never `rich` directly —
so layout, spinner, and progress changes land in one place.
"""

from docspatch.ui.console import console, err_console
from docspatch.ui.panels import cost_panel, kv_panel, warning_panel
from docspatch.ui.progress import progress_bar
from docspatch.ui.prompter import Prompter, QuestionaryPrompter, ScriptedPrompter, aprompt
from docspatch.ui.status import status
from docspatch.ui.summary import cache_hit_row, cost_rows, render_summary
from docspatch.ui.tables import build_table

__all__ = [
    "Prompter",
    "QuestionaryPrompter",
    "ScriptedPrompter",
    "aprompt",
    "build_table",
    "cache_hit_row",
    "console",
    "cost_panel",
    "cost_rows",
    "err_console",
    "kv_panel",
    "progress_bar",
    "render_summary",
    "status",
    "warning_panel",
]
