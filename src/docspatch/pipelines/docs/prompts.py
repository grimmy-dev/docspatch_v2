"""Generate prompt strings for docstring creation tasks using specific formatting guidelines and tone requirements."""

from pydantic import BaseModel, ConfigDict

from docspatch.constants import DEFAULT_TONE, TONES

BANNED_PHRASES: tuple[str, ...] = (
    "This function",
    "This method",
    "This class",
    "simply",
    "essentially",
    "in order to",
    "the purpose of",
    "as the name suggests",
    "basically",
    "just",
    "leverage",
    "facilitate",
    "utilize",
    "responsible for",
    "is used to",
    "used to",
    "allows you to",
    "a function that",
    "a method that",
)


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
    """Format a specific target as an input entry in the generation prompt.

    Args:
        item: Target data including source code and optional feedback.

    Returns:
        Formatted entry string.
    """
    head = f"--- id: {item.key} ---\nSignature:\n{item.signature}\n\nBody:\n{item.body}"
    if not item.feedback:
        return head
    notes = "\n".join(f"- {n}" for n in item.feedback)
    return f"{head}\n\nReviewer feedback (address every note, newest is most recent):\n{notes}"


def contains_banned_phrase(text: str) -> bool:
    """Check text for forbidden phrasing.

    Args:
        text: String to evaluate.

    Returns:
        Boolean indicating existence of banned phrases.
    """
    lowered = text.lower()
    return any(phrase.lower() in lowered for phrase in BANNED_PHRASES)


def build_batch_docstring_prompt(items: list[DocstringItem], tone: str, remarks: str | None = None) -> str:
    """Create a complete prompt text for a batch of documentation targets.

    Args:
        items: List of items requiring docstrings.
        tone: Requested stylistic tone.
        remarks: Additional instructions to apply to all targets.

    Returns:
        The constructed prompt.
    """
    tone_line = TONES.get(tone, TONES[DEFAULT_TONE])
    banned = ", ".join(repr(p) for p in BANNED_PHRASES)
    sections = "\n\n".join(render_item(item) for item in items)
    ids = "\n".join(f"- {item.key}" for item in items)
    remarks_line = f"- Extra instruction (applies to every entry): {remarks}\n" if remarks else ""
    return (
        "Write a Google-style docstring for EACH entry below by filling the structured fields and be non LLM-ese.\n"
        "Map each `id` exactly to its docstring spec in the `docstrings` field.\n"
        "How to fill each spec:\n"
        f"- Tone: {tone_line}\n"
        f"{remarks_line}"
        "- description: one line, imperative mood, ending with a period. Say what it does — "
        "plain, concrete verbs, no meta-commentary about the code being a function.\n"
        "- args: one entry per parameter worth explaining; skip self/cls and self-evident ones.\n"
        "- returns: what it returns; leave null for functions that return None.\n"
        "- raises: only exceptions a caller should anticipate; leave empty when none.\n"
        '- A module entry (id ending in "::<module>"): set description to a 1–3 sentence '
        "summary of the module's role and leave args, returns, and raises empty.\n"
        f"- Banned phrases (never use): {banned}.\n\n"
        f"Expected ids (use each verbatim as a key in `docstrings`):\n{ids}\n\n"
        f"Entries:\n{sections}\n"
    )
