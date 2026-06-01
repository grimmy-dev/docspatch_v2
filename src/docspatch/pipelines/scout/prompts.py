"""Construct prompt templates for analyzing and summarizing code files within the scout pipeline."""

from collections.abc import Sequence

from docspatch.pipelines.scout.state import FileMiss

PATH_HEADER = "===== PATH: {path} ====="


def render_file_block(miss: FileMiss) -> str:
    """Generate a formatted block containing file content and optional prior summary data.

    Args:
        miss: The file miss data containing source and potential prior state.

    Returns:
        The rendered string block.
    """
    head = f"{PATH_HEADER.format(path=miss.path)}\n{miss.compressed}"
    if miss.prior is None:
        return head
    return f"{head}\n--- Previous summary: {miss.prior.summary}\n--- Previous code:\n{miss.prior.compressed}"


def build_batch_prompt(misses: Sequence[FileMiss]) -> str:
    """Construct a prompt for summarizing a batch of files.

    Args:
        misses: The collection of files missing from cache.

    Returns:
        The complete prompt string.
    """
    paths = "\n".join(f"- {m.path}" for m in misses)
    blocks = "\n\n".join(render_file_block(m) for m in misses)
    change_line = (
        "For any file that shows a Previous summary and Previous code, also set "
        "`change_note`: one line on what changed. Leave change_note empty for "
        "files without previous context.\n"
        if any(m.prior for m in misses)
        else ""
    )
    return (
        "Summarize each Python module below.\n"
        "For each file: a 3-4 sentence summary (purpose, key abstractions, data "
        "flow, notable behaviour); `interfaces` (public functions/classes/exports "
        "a caller uses); `relationships` (what it depends on and what depends on it).\n"
        "For each function: 2 sentences — what it does and what it returns or raises.\n"
        "Start all summaries with a verb. No filler, no LLM-ese.\n"
        f"{change_line}\n"
        f"Expected paths:\n{paths}\n\n"
        f"{blocks}"
    )
