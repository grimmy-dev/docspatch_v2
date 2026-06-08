"""Formatter utilities and templates to generate LLM instructions for docstring batches."""

from pydantic import BaseModel, ConfigDict

from docspatch.constants import DEFAULT_TONE, TONES


class DocstringItem(BaseModel):
    """One function's prompt payload. ``key`` doubles as the response dict key.

    ``feedback`` holds reviewer notes accumulated across rerun rounds (oldest first).
    """

    model_config = ConfigDict(frozen=True)

    key: str
    signature: str
    body: str
    feedback: tuple[str, ...] = ()


def render_item(item: DocstringItem) -> str:
    """Format a code target into a text section for an LLM prompt.

    Args:
        item: Code target details and historical feedback notes.

    Returns:
        Plaintext block with key, signature, body, and feedback comments.
    """
    head = f"--- id: {item.key} ---\nSignature:\n{item.signature}\n\nBody:\n{item.body}"
    if not item.feedback:
        return head
    notes = "\n".join(f"- {n}" for n in item.feedback)
    return f"{head}\n\nReviewer feedback (address every note, newest is most recent):\n{notes}"


# Few-shot bad->good pairs anchor the style far better than a rule list alone. The
# banned phrases are enforced in code (docstring_quality.needs_rewrite), so they are
# not re-listed here — keeping the per-call prompt lean.
DOCSTRING_GUIDANCE = (
    "You are an experienced engineer writing Google-style docstrings that maintainers and "
    "AI agents navigating this repo will rely on.\n"
    "Fill the structured fields for EACH entry; map each `id` exactly to its spec in `docstrings`.\n\n"
    "Quality bar:\n"
    "- description: ONE line, imperative mood, ending with a period. Lead with the concrete "
    "action and name the real mechanism, using the codebase's own terminology. State what the "
    "code does and, when non-obvious, why — not that it is code.\n"
    "- Be precise and specific: prefer the exact behaviour over a general category.\n"
    "- Do not open with a vague verb (Manage, Handle, Provide, Orchestrate, Coordinate, "
    "Implement, Enable, Support, Define) — say the specific thing instead.\n"
    "- Do not restate the name, add meta-commentary, hedge, or pad with marketing adjectives "
    "(robust, powerful, seamless, comprehensive).\n\n"
    "Examples (bad -> good):\n"
    "- function:\n"
    "  bad:  Manage the asynchronous generation of docstrings through a distributed state graph.\n"
    "  good: Run one LLM call per batch, fanned out with Send, and checkpoint each result.\n"
    "- function:\n"
    "  bad:  Provide utilities for estimating and calculating LLM costs.\n"
    "  good: Convert token counts to dollar cost from the per-model price table.\n"
    "- module:\n"
    "  bad:  Define the internal data structures for tracking run progress.\n"
    "  good: Dataclasses for scan plans, file misses, and per-batch results.\n\n"
    "Field rules:\n"
    "- args: one entry per parameter worth explaining; skip self/cls and self-evident ones.\n"
    "- returns: what it returns; leave null when the function returns None.\n"
    "- raises: only exceptions a caller should anticipate; leave empty when none.\n"
    '- A module entry (id ending in "::<module>"): description is 1-2 sentences naming what the '
    "module concretely contains or does (key types, functions, or data flow), not a role label. "
    "Leave args, returns, and raises empty.\n"
)


def build_batch_docstring_prompt(items: list[DocstringItem], tone: str, remarks: str | None = None) -> str:
    """Compose a comprehensive system prompt and instruction list for a batch of documentation targets.

    Args:
        items: Collection of target elements requiring docstrings.
        tone: Target writing style name.
        remarks: Extra custom instructions to prepend to the batch prompt.

    Returns:
        The fully formatted prompt string ready for LLM consumption.
    """
    tone_line = TONES.get(tone, TONES[DEFAULT_TONE])
    sections = "\n\n".join(render_item(item) for item in items)
    ids = "\n".join(f"- {item.key}" for item in items)
    remarks_line = f"- Extra instruction (applies to every entry): {remarks}\n" if remarks else ""
    return (
        f"{DOCSTRING_GUIDANCE}"
        f"- Tone: {tone_line}\n"
        f"{remarks_line}\n"
        f"Expected ids (use each verbatim as a key in `docstrings`):\n{ids}\n\n"
        f"Entries:\n{sections}\n"
    )
