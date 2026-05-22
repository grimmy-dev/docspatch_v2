"""License catalogue. Maps SPDX identifiers to LICENSE file bodies.

The license texts are large static blobs, so they live as plain ``.txt`` files
under ``docspatch/resources/licenses/`` rather than in source. This module is
only the identifier list and the lookup.
"""

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
    """SPDX-style identifiers for every license docspatch can write."""
    return list(LICENSE_IDS)


def text(name: str) -> str | None:
    """Return the LICENSE file body for ``name``.

    Returns ``None`` for ``Proprietary`` (no body) or any unknown identifier.
    """
    if name not in LICENSE_IDS:
        return None
    resource = _LICENSE_DIR.joinpath(f"{name}.txt")
    if not resource.is_file():
        return None
    return resource.read_text(encoding="utf-8")
