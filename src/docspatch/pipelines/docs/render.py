"""Convert structured documentation specs into rendered text strings. This module ensures consistency and proper Google-style formatting."""

from docspatch.schemas import DocstringSpec


def render_google_docstring(spec: DocstringSpec) -> str:
    """Assemble a structured specification into a final Google-style docstring.

    Args:
        spec: Parsed docstring components.

    Returns:
        The complete docstring text.
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
    """Ensure a string ends with a period.

    Args:
        text: String to validate.

    Returns:
        String with appropriate terminal punctuation.
    """
    trimmed = text.strip()
    if trimmed and trimmed[-1] not in ".!?":
        return trimmed + "."
    return trimmed
