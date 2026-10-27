import logging
import re
import sys
from collections.abc import MutableMapping
from typing import Any, cast

import structlog
from structlog.types import EventDict

from app.core.config import settings

SENSITIVE_KEYS = {
    "password",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "authorization",
    "encryption_key",
    "cookie",
}

SENSITIVE_PATTERN = re.compile(
    r"(password|secret|token|api_?key|authorization)",
    re.IGNORECASE,
)


def filter_sensitive_data(
    logger: Any,
    method_name: str,
    event_dict: MutableMapping[str, Any],
) -> EventDict:
    """Censor any sensitive keys or values from structlog event dictionary."""
    for key in list(event_dict.keys()):
        if SENSITIVE_PATTERN.search(key):
            event_dict[key] = "[REDACTED]"
    return event_dict


def setup_logging() -> None:
    """Initialize structured logging using structlog with security filters."""
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        filter_sensitive_data,
    ]

    if settings.APP_ENV == "production":
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[
            processor
            for processor in shared_processors
            if processor is not structlog.stdlib.filter_by_level
        ],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(logging.INFO if not settings.DEBUG else logging.DEBUG)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a named structured logger instance."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))
