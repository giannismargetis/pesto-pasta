"""Logging: rotating file log + concise console output."""

from __future__ import annotations

import logging
import logging.handlers
import sys

_ROOT = "pesto"
_configured = False


def setup_logging(level: str = "INFO", console: bool = True) -> None:
    global _configured
    if _configured:
        return
    _configured = True
    from . import paths

    paths.LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s.%(msecs)03d %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    file_handler = logging.handlers.RotatingFileHandler(
        paths.LOG_DIR / "pesto.log", maxBytes=5 * 2**20, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    handlers: list[logging.Handler] = [file_handler]
    if console and sys.stdout is not None:
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(logging.Formatter("%(asctime)s %(levelname).1s %(name)s: %(message)s", "%H:%M:%S"))
        handlers.append(stream)
    for name in (_ROOT, "pasta"):
        logger = logging.getLogger(name)
        logger.setLevel(getattr(logging, level.upper(), logging.INFO))
        for h in handlers:
            logger.addHandler(h)
        logger.propagate = False


def get_logger(name: str = "") -> logging.Logger:
    return logging.getLogger(f"{_ROOT}.{name}" if name else _ROOT)
