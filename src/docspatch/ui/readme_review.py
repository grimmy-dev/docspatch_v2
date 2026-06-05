"""Interactive terminal loop for validating and refining README drafts with user feedback."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from rich.markdown import Markdown
from rich.panel import Panel

from docspatch.llm import TokenUsage
from docspatch.ui.console import console, status
from docspatch.ui.diff import render_diff
from docspatch.ui.prompter import Prompter, aprompt

ACCEPT = "accept"
REVISE = "revise"
CANCEL = "cancel"

# Given accumulated feedback, produce a fresh README and the tokens it cost.
Regenerate = Callable[[tuple[str, ...]], Awaitable[tuple[str, TokenUsage]]]


@dataclass(frozen=True)
class ReviewResult:
    """Outcome of a README review session.

    ``markdown`` is the accepted document, or null when the user cancelled.
    ``usage`` totals every generation, including discarded revisions.
    """

    accepted: bool
    markdown: str | None
    usage: TokenUsage


def render_readme(markdown: str, existing: str | None) -> None:
    """Show what the review changes: a red/green diff, or a full preview when new.

    Args:
        markdown: The generated document.
        existing: The current README, or null when none exists yet.
    """
    if existing:
        console.print(Panel(render_diff(existing, markdown), title="README changes", border_style="cyan"))
    else:
        console.print(Panel(Markdown(markdown), title="README preview", border_style="cyan"))


def _prompt_action(prompter: Prompter) -> str:
    """Query the user for a revision action selection.

    Args:
        prompter: The interface for terminal user input.

    Returns:
        The chosen action constant string.
    """
    return str(
        prompter.select(
            "README ready. How should docspatch proceed?",
            {"Accept & write": ACCEPT, "Revise (give feedback)": REVISE, "Cancel": CANCEL},
        )
    )


async def review_readme(
    prompter: Prompter, regenerate: Regenerate, *, existing: str | None = None, max_revisions: int = 3
) -> ReviewResult:
    """Loop through README generation, previewing, and user-led revision until acceptance or cancellation.

    A safety bound: after ``max_revisions`` revise rounds the latest draft is
    accepted and written so the loop can never run unbounded.

    Args:
        prompter: The interface for collecting user input and feedback.
        regenerate: Callback to produce a new README version based on existing feedback history.
        existing: The current README, shown as a diff baseline; null for a first-time README.
        max_revisions: Revise rounds allowed before the latest draft is auto-accepted.

    Returns:
        The outcome of the review process including usage metrics and the final document.
    """
    feedback: tuple[str, ...] = ()
    with status("Generating README…"):
        markdown, usage = await regenerate(feedback)
    while True:
        render_readme(markdown, existing)
        # Prompts run in a worker thread: questionary opens its own event loop,
        # which would clash with the one already running this coroutine.
        action = await aprompt(_prompt_action, prompter)
        if action == ACCEPT:
            return ReviewResult(accepted=True, markdown=markdown, usage=usage)
        if action == CANCEL:
            return ReviewResult(accepted=False, markdown=None, usage=usage)
        note = (await aprompt(prompter.text, "What should change? (blank to keep as is):")).strip()
        if not note:
            continue  # nothing to act on — re-show the same document
        feedback += (note,)
        with status("Revising README…"):
            markdown, round_usage = await regenerate(feedback)
        usage += round_usage
        if len(feedback) >= max_revisions:
            console.print(f"[yellow]Revision limit ({max_revisions}) reached — writing the latest draft.[/yellow]")
            return ReviewResult(accepted=True, markdown=markdown, usage=usage)
