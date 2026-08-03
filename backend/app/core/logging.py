"""
Structured logging setup (structlog with JSON output in production).
"""
from __future__ import annotations

import logging
import sys
from typing import Any, Dict

import structlog

from app.core.config import settings


def _configure_processors(environment: str) -> list:
    shared = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]
    if environment == "development" or settings.LOG_FORMAT == "console":
        shared += [
            structlog.dev.set_exc_info,
            structlog.dev.ConsoleRenderer(colors=True),
        ]
    else:
        shared += [
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(serializer=_json_default),
        ]
    return shared


def _json_default(value: Any) -> str:
    if isinstance(value, Exception):
        return str(value)
    return str(value)


def setup_logging() -> None:
    """Configure structlog and stdlib logging."""
    structlog.configure(
        processors=_configure_processors(settings.ENVIRONMENT),
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Route stdlib logs through structlog
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    )

    # Quiet noisy third-party loggers
    for name in ("uvicorn.access", "httpx", "httpcore", "aioredis", "watchfiles"):
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound structured logger."""
    return structlog.get_logger(name)


def bind_context(**kwargs: Dict[str, Any]) -> None:
    """Bind context vars for the current request/task."""
    structlog.contextvars.bind_contextvars(**kwargs)


def unbind_context() -> None:
    """Clear all bound context vars."""
    structlog.contextvars.unbind_contextvars()
