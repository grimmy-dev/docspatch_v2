"""Formatter functions to serialize raw docstring components into standard Python styles."""

from docspatch.schemas import DocstringSpec


def render_google_docstring(spec: DocstringSpec) -> str:
    """Format structured docstring specifications into Google-style documentation blocks.

    Args:
        spec: Structured description, argument, return, and raise schemas.

    Returns:
        A single formatted docstring block.
    """
    summary = _period(spec.description)
    sections: list[str] = []

    if spec.args:
        lines = ["Args:"]
        lines.extend(f"    {arg.name}: {_period(arg.description)}" for arg in spec.args)
        sections.append("\n".join(lines))

    if spec.returns and spec.returns.strip():
        sections.append(f"Returns:\n    {_period(spec.returns.strip())}")

    if spec.raises:
        lines = ["Raises:"]
        lines.extend(f"    {exc.exception}: {_period(exc.when)}" for exc in spec.raises)
        sections.append("\n".join(lines))

    if not sections:
        return summary
    return summary + "\n\n" + "\n\n".join(sections)


def _period(text: str) -> str:
    """Append a period to a string if it lacks terminal punctuation.

    Args:
        text: Text to finalize.

    Returns:
        Cleaned text ending with a period, exclamation point, or question mark.
    """
    trimmed = text.strip()
    if trimmed and trimmed[-1] not in ".!?":
        return trimmed + "."
    return trimmed
