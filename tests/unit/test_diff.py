"""Shared diff renderer: additions green, removals red, unchanged dim."""

from docspatch.ui.diff import render_diff


def _styled(before: str, after: str) -> list[tuple[str, str]]:
    """Render the diff and return (style, text) spans for assertions."""
    text = render_diff(before, after)
    return [(str(span.style), text.plain[span.start : span.end]) for span in text.spans]


def test_added_line_is_green():
    spans = _styled("a\n", "a\nb\n")
    assert any(style == "green" and "+ b" in chunk for style, chunk in spans)


def test_removed_line_is_red():
    spans = _styled("a\nb\n", "a\n")
    assert any(style == "red" and "- b" in chunk for style, chunk in spans)


def test_unchanged_line_is_dim():
    spans = _styled("a\n", "a\nb\n")
    assert any(style == "dim" and "  a" in chunk for style, chunk in spans)


def test_first_time_readme_is_all_additions():
    spans = _styled("", "# Title\nbody\n")
    assert spans
    assert all(style == "green" for style, _ in spans)


def test_intraline_hint_lines_are_dropped():
    # Differ emits "? " lines for changed words; they must not surface.
    out = render_diff("hello world\n", "hello there\n").plain
    assert "?" not in out
