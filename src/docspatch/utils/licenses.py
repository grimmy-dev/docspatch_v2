"""Provide access to standard software license templates."""

from importlib.resources import files

# Ordered so the picker shows the most common choices first.
# "Proprietary" has no text body — it sets the pyproject field only.
LICENSE_IDS: tuple[str, ...] = (
    "MIT",
    "Apache-2.0",
    "GPL-3.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "MPL-2.0",
    "Unlicense",
    "Proprietary",
)

_LICENSE_DIR = files("docspatch.resources").joinpath("licenses")


def available() -> list[str]:
    """List the identifiers for all supported licenses.

    Returns:
        A list of license names.
    """
    return list(LICENSE_IDS)


def insert_copyright(body: str, name: str, year: int) -> str:
    """Add a copyright line after the license title if absent.

    Args:
        body: The original license text.
        name: The copyright holder name.
        year: The copyright year.

    Returns:
        The updated license text.
    """
    if "Copyright (c)" in body:
        return body
    lines = body.splitlines()
    if not lines:
        return body
    lines.insert(1, f"\nCopyright (c) {year} {name}")
    return "\n".join(lines) + "\n"


def text(name: str) -> str | None:
    """Retrieve the full text of a specific license.

    Args:
        name: License identifier.

    Returns:
        The text content or null if unavailable.
    """
    if name not in LICENSE_IDS:
        return None
    resource = _LICENSE_DIR.joinpath(f"{name}.txt")
    if not resource.is_file():
        return None
    return resource.read_text(encoding="utf-8")
