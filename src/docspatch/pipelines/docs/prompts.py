"""Docs pipeline prompts. Single source of truth for wording.

Banned-phrase list keeps generated docstrings free of LLM-ese filler. The same
list is used post-hoc to trigger silent retries.
"""

from pydantic import BaseModel, ConfigDict

from docspatch.constants import DEFAULT_TONE, TONES

BANNED_PHRASES: tuple[str, ...] = (
    "This function",
    "simply",
    "essentially",
    "in order to",
    "the purpose of",
    "as the name suggests",
    "basically",
    "just",
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
    """Render one function block + its accumulated reviewer feedback."""
    head = f"--- id: {item.key} ---\nSignature:\n{item.signature}\n\nBody:\n{item.body}"
    if not item.feedback:
        return head
    notes = "\n".join(f"- {n}" for n in item.feedback)
    return f"{head}\n\nReviewer feedback (address every note, newest is most recent):\n{notes}"


def contains_banned_phrase(text: str) -> bool:
    """Return ``True`` if ``text`` contains any banned phrase (case-insensitive)."""
    lowered = text.lower()
    return any(phrase.lower() in lowered for phrase in BANNED_PHRASES)


def build_batch_docstring_prompt(
    items: list[DocstringItem], tone: str, remarks: str | None = None
) -> str:
    """Bundle N functions into one structured-output prompt.

    Args:
        items: Functions to document. ``key`` must match the response dict key.
        tone: Tone key from config. Falls back to default tone guidance.
        remarks: Optional run-wide instruction applied to every docstring.
    """
    tone_line = TONES.get(tone, TONES[DEFAULT_TONE])
    banned = ", ".join(repr(p) for p in BANNED_PHRASES)
    sections = "\n\n".join(render_item(item) for item in items)
    ids = "\n".join(f"- {item.key}" for item in items)
    remarks_line = f"- Extra instruction (applies to every docstring): {remarks}\n" if remarks else ""
    return (
        "Write a Google-style docstring for EACH function below.\n"
        "Return a JSON object whose `docstrings` field maps each `id` exactly to its docstring body.\n"
        "Rules:\n"
        f"- Tone: {tone_line}\n"
        f"{remarks_line}"
        "- Start each with a one-line summary in the imperative mood, ending with a period.\n"
        "- After the summary, leave a blank line before any section.\n"
        "- Section headers (Args:, Returns:, Raises:, Notes:) on their own line.\n"
        "- Each parameter under Args: on its own line, indented 4 spaces: `name: description.`\n"
        "- Include Args / Returns / Raises sections only when they add information.\n"
        "- Use real newline characters between lines — never collapse to one line.\n"
        f"- Banned phrases (do not use): {banned}.\n"
        "- No triple quotes in the output. No filler. No restating the function name.\n\n"
        f"Expected ids (use each verbatim as a key in `docstrings`):\n{ids}\n\n"
        f"Functions:\n{sections}\n"
    )
