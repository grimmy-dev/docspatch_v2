"""Terminal UI: progress bars, panels, diff renderers, and prompters."""

from docspatch.ui.console import command_timer, console, err_console, status, suspend_timer, timed_status
from docspatch.ui.panels import cost_panel, kv_panel, warning_panel
from docspatch.ui.progress import progress_bar
from docspatch.ui.prompter import Prompter, QuestionaryPrompter, ScriptedPrompter, aprompt, confirm_or_skip
from docspatch.ui.summary import cache_hit_row, cost_rows, render_summary
from docspatch.ui.tables import build_table

__all__ = [
    "Prompter",
    "QuestionaryPrompter",
    "ScriptedPrompter",
    "aprompt",
    "build_table",
    "cache_hit_row",
    "command_timer",
    "confirm_or_skip",
    "console",
    "cost_panel",
    "cost_rows",
    "err_console",
    "kv_panel",
    "progress_bar",
    "render_summary",
    "status",
    "suspend_timer",
    "timed_status",
    "warning_panel",
]
