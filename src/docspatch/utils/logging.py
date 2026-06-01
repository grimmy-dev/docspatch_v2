"""Define logging configuration and retrieval helpers."""

from __future__ import annotations

import logging
import sys

LOGGER_NAME = "docspatch"

_LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DATE_FORMAT = "%H:%M:%S"


def configure_logging(debug: bool) -> None:
    """Set up the main application logging behavior.

    Args:
        debug: Enable verbose debugging output if true.
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
    """Create a scoped logger instance.

    Args:
        name: Component name for the logger namespace.

    Returns:
        A configured logging instance.
    """
    return logging.getLogger(f"{LOGGER_NAME}.{name}")
