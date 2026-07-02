"""Application-wide logging configuration.

Centralizes log formatting so every service/router uses the same shape.
Call ``configure_logging()`` exactly once during FastAPI startup.
"""

import logging
import logging.config
import sys
from typing import Any

LOG_FORMAT = (
    "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
)
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def configure_logging(level: str = "INFO") -> None:
    """Configure root + application loggers.

    Idempotent: re-invocation is a no-op (safe for FastAPI reloaders and
    pytest-asyncio reruns).

    Args:
        level: Minimum level for the application logger
            (``mission_control_v2`` and descendants). Root stays at WARNING
            so noisy third-party libs do not flood stdout.
    """
    global _configured
    if _configured:
        return

    config: dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": LOG_FORMAT,
                "datefmt": DATE_FORMAT,
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "stream": sys.stdout,
                "formatter": "standard",
                "level": "DEBUG",
            },
        },
        "loggers": {
            "": {
                "handlers": ["console"],
                "level": "WARNING",
            },
            "mission_control_v2": {
                "level": level,
                "propagate": True,
            },
            "mission_control_v2.access": {
                "level": "INFO",
                "propagate": True,
            },
            "uvicorn.error": {"level": "INFO", "propagate": True},
            "uvicorn.access": {"level": "WARNING", "propagate": True},
            "sqlalchemy.engine": {"level": "WARNING", "propagate": True},
        },
    }
    logging.config.dictConfig(config)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger under ``mission_control_v2``.

    Args:
        name: Module name (typically ``__name__``).

    Returns:
        A logger that inherits the application-level handlers and level.
    """
    if name == "__main__" or not name.startswith("mission_control_v2"):
        name = f"mission_control_v2.{name}"
    return logging.getLogger(name)
