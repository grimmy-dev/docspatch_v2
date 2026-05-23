"""Filesystem utilities."""

import os
from pathlib import Path


def atomic_write(path: Path, content: str | bytes) -> None:
    """Write ``content`` to ``path`` atomically."""
    # Cancellation contract: path is fully written or fully unchanged — write
    # goes to .tmp first, then os.replace (atomic on POSIX + Windows). On any
    # error or interrupt the .tmp is removed and the exception re-raised.
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        if isinstance(content, bytes):
            tmp.write_bytes(content)
        else:
            tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
