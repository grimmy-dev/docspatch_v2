"""Reusable rich-based UI primitives.

Commands and pipeline nodes import from here only — never `rich` directly —
so layout, spinner, and progress changes land in one place.
"""

from docspatch.ui.console import console, err_console
from docspatch.ui.panels import kv_panel
from docspatch.ui.progress import progress_bar
from docspatch.ui.prompter import Prompter, QuestionaryPrompter, ScriptedPrompter, aprompt
from docspatch.ui.status import status
from docspatch.ui.tables import build_table

__all__ = [
    "Prompter",
    "QuestionaryPrompter",
    "ScriptedPrompter",
    "aprompt",
    "build_table",
    "console",
    "err_console",
    "kv_panel",
    "progress_bar",
    "status",
]
