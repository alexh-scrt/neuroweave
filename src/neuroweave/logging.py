"""NeuroWeave structured logging — configures structlog for the entire application."""

from __future__ import annotations

import logging
import sys

import structlog

from neuroweave.config import LogFormat, NeuroWeaveConfig


def configure_logging(config: NeuroWeaveConfig) -> None:
    """Configure structlog and stdlib logging from NeuroWeave config.

    Call once at startup from main.py. After this, any module can do:

        import structlog
        log = structlog.get_logger()
        log.info("extraction.complete", entities=3, ms=42)

    Args:
        config: NeuroWeave configuration (log_level, log_format).
    """
    log_level = getattr(logging, config.log_level.upper(), logging.INFO)

    # Shared processors — run for every log event
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=False),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if config.log_format == LogFormat.JSON:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure stdlib root logger so structlog output actually appears
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    # Quiet noisy third-party loggers
    for name in ("uvicorn", "uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(name).setLevel(max(log_level, logging.WARNING))


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a structlog logger, optionally bound to a component name.

    Args:
        name: Component name (e.g. "extraction", "graph"). Added as 'component' key.

    Returns:
        A bound structlog logger.
    """
    log = structlog.get_logger()
    if name:
        log = log.bind(component=name)
    return log
