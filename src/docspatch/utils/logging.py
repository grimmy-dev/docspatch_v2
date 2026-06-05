"""Configures the root logging stream format and retrieves child loggers."""

from __future__ import annotations

import logging
import sys

LOGGER_NAME = "docspatch"

_LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DATE_FORMAT = "%H:%M:%S"


def configure_logging(debug: bool) -> None:
    """Configure the root docspatch logger to write formatted logs to standard error.

    Args:
        debug: Enable verbose debug logging levels.
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
    """Retrieve a child logger under the docspatch namespace.

    Args:
        name: Suffix name of the logger category.

    Returns:
        Configured Logger instance.
    """
    return logging.getLogger(f"{LOGGER_NAME}.{name}")
