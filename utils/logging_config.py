"""
Structured logging configuration for InfoDigest Bot.
Uses structlog for structured, JSON-capable logging.
"""

import logging
import sys
from typing import Optional

import structlog


def configure_logging(
    log_level: str = "INFO",
    json_format: bool = False,
    log_file: Optional[str] = None
) -> None:
    """
    Configure structured logging for the application.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        json_format: If True, output logs in JSON format (for production)
        log_file: Optional file path to write logs to
    """
    # Set up standard logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )

    # Configure processors based on environment
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if json_format:
        # Production: JSON output
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer()
        ]
    else:
        # Development: Console output with colors
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True)
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Set up file handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))
        logging.getLogger().addHandler(file_handler)


def get_logger(name: str = __name__) -> structlog.stdlib.BoundLogger:
    """
    Get a structured logger instance.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Configured structlog logger
    """
    return structlog.get_logger(name)


# Convenience function for logging with context
def bind_context(**kwargs) -> None:
    """
    Bind context variables for all subsequent log calls in this context.

    Args:
        **kwargs: Key-value pairs to add to log context
    """
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_context() -> None:
    """Clear all bound context variables."""
    structlog.contextvars.clear_contextvars()
