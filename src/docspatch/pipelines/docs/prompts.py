"""Generate prompt strings for docstring creation tasks using specific formatting guidelines and tone requirements."""

import re

from pydantic import BaseModel, ConfigDict

from docspatch.constants import DEFAULT_TONE, TONES

# Only high-precision meta-tells that are never legitimate in a one-line docstring.
# Matched on word boundaries (see contains_banned_phrase), so short words can't hit
# substrings like "adjust". Vagueness is handled by the examples + WEAK_OPENERS, not
# by enumerating adjectives here.
BANNED_PHRASES: tuple[str, ...] = (
    "this function",
    "this method",
    "this class",
    "this module",
    "as the name suggests",
    "responsible for",
    "in order to",
    "the purpose of",
    "allows you to",
    "a function that",
    "a method that",
)

_BANNED_RE = re.compile(r"\b(?:" + "|".join(re.escape(p) for p in BANNED_PHRASES) + r")\b")

# Vague openers that say nothing concrete. Checked as the first word of a
# description, not as a substring, so "manage"/"define" remain usable mid-sentence.
WEAK_OPENERS: frozenset[str] = frozenset(
    {
        "manage",
        "handle",
        "provide",
        "orchestrate",
        "coordinate",
        "implement",
        "enable",
        "support",
        "define",
        "deal",
        "perform",
    }
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
    """Check text for forbidden phrasing on word boundaries.

    Args:
        text: String to evaluate.

    Returns:
        True when a banned meta-phrase appears as a whole word or phrase.
    """
    return _BANNED_RE.search(text.lower()) is not None


def opens_with_weak_verb(text: str) -> bool:
    """Check whether the first word of a description is a vague opener.

    Args:
        text: The rendered description or docstring to inspect.

    Returns:
        True when the leading word is one of the weak openers.
    """
    stripped = text.strip()
    if not stripped:
        return False
    return stripped.split(maxsplit=1)[0].strip(":,.").lower() in WEAK_OPENERS


def needs_rewrite(text: str) -> bool:
    """Report whether a generated docstring trips a style guardrail.

    Args:
        text: The rendered docstring to check.

    Returns:
        True when it contains a banned phrase or opens with a weak verb.
    """
    return contains_banned_phrase(text) or opens_with_weak_verb(text)


# Few-shot bad->good pairs anchor the style far better than a rule list alone. The
# banned phrases are enforced in code (needs_rewrite), so they are not re-listed
# here — keeping the per-call prompt lean.
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
    """Create a complete prompt text for a batch of documentation targets.

    Args:
        items: List of items requiring docstrings.
        tone: Requested stylistic tone.
        remarks: Additional instructions to apply to all targets.

    Returns:
        The constructed prompt.
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
