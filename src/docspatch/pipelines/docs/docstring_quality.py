"""Style guardrails that decide whether a generated docstring must be regenerated."""

import re

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


def contains_banned_phrase(text: str) -> bool:
    """Determine if a string contains any phrasing explicitly prohibited in docstrings.

    Args:
        text: Text string to evaluate.

    Returns:
        True if a forbidden phrase is detected, false otherwise.
    """
    return _BANNED_RE.search(text.lower()) is not None


def opens_with_weak_verb(text: str) -> bool:
    """Determine if a string begins with a vague action verb.

    Args:
        text: Text string to evaluate.

    Returns:
        True if the leading word is in the weak verb set, false otherwise.
    """
    stripped = text.strip()
    if not stripped:
        return False
    return stripped.split(maxsplit=1)[0].strip(":,.").lower() in WEAK_OPENERS


def needs_rewrite(text: str) -> bool:
    """Identify whether a candidate docstring fails quality checks and must be regenerated.

    Args:
        text: Generated docstring text.

    Returns:
        True if the docstring violates any style rule, false otherwise.
    """
    return contains_banned_phrase(text) or opens_with_weak_verb(text)
