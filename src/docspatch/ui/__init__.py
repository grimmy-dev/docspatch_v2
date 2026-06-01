"""Expose the UI components for user interaction and status reporting."""

from docspatch.ui.console import console, err_console, status
from docspatch.ui.panels import cost_panel, kv_panel, warning_panel
from docspatch.ui.progress import progress_bar
from docspatch.ui.prompter import Prompter, QuestionaryPrompter, ScriptedPrompter, aprompt
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
