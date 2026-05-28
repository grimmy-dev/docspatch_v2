"""Logging setup. ``--debug`` turns on a step-by-step trace of a run.

Without ``--debug`` only warnings and errors reach stderr. With it, every
step logs at DEBUG so a user can follow the whole flow when reporting a bug.
"""

from __future__ import annotations

import logging
import sys

LOGGER_NAME = "docspatch"

_LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DATE_FORMAT = "%H:%M:%S"


def configure_logging(debug: bool) -> None:
    """Configure the ``docspatch`` logger for the current run.

    Args:
        debug: When true, log at DEBUG with a readable per-step trace;
            otherwise only WARNING and above surface.
    """
    level = logging.DEBUG if debug else logging.WARNING
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.handlers.clear()

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    logger.addHandler(handler)
    logger.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the ``docspatch`` namespace."""
    return logging.getLogger(f"{LOGGER_NAME}.{name}")
