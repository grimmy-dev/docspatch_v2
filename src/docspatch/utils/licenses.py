"""Loads standard license templates from package resources and inserts copyright headers."""

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
    """Get the identifiers of all supported licenses.

    Returns:
        List of standard license identifier strings.
    """
    return list(LICENSE_IDS)


def insert_copyright(body: str, name: str, year: int) -> str:
    """Insert a copyright notice line immediately below the license header if missing.

    Args:
        body: Full text of the license template.
        name: Copyright holder's name.
        year: Copyright declaration year.

    Returns:
        Modified license text containing the copyright notice.
    """
    if "Copyright (c)" in body:
        return body
    lines = body.splitlines()
    if not lines:
        return body
    lines.insert(1, f"\nCopyright (c) {year} {name}")
    return "\n".join(lines) + "\n"


def text(name: str) -> str | None:
    """Load the template text of a supported license from package resources.

    Args:
        name: Supported license identifier.

    Returns:
        Content of the license text file, or null if not found.
    """
    if name not in LICENSE_IDS:
        return None
    resource = _LICENSE_DIR.joinpath(f"{name}.txt")
    if not resource.is_file():
        return None
    return resource.read_text(encoding="utf-8")
