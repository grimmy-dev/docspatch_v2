"""Implements a diff renderer that formats code changes with Rich styles."""

import difflib

from rich.text import Text

# Differ tags the two-character prefix on every line; we keep these three and
# drop "? " hint lines, which only annotate intraline changes.
_STYLES = {"+ ": ("green", "+"), "- ": ("red", "-"), "  ": ("dim", " ")}


def render_diff(before: str, after: str) -> Text:
    """Build a line diff showing additions in green and removals in red.

    Args:
        before: The prior text.
        after: The new text.

    Returns:
        A Rich Text object with styled diff output.
    """
    text = Text()
    for line in difflib.Differ().compare(before.splitlines(), after.splitlines()):
        tag = line[:2]
        if tag not in _STYLES:
            continue  # "? " intraline-hint lines carry no content to show
        style, gutter = _STYLES[tag]
        text.append(f"{gutter} {line[2:]}\n", style=style)
    return text
