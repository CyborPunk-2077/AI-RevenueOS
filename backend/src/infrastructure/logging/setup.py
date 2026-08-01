"""structlog configuration: JSON in every deployed environment, console locally."""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from infrastructure.logging.context import current_context
from infrastructure.logging.redaction import redact


def _inject_context(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    for key, value in current_context().items():
        if value is not None and key not in event_dict:
            event_dict[key] = value
    return event_dict


def _redact_processor(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    scrubbed: dict[str, Any] = redact(event_dict, mask_pii=True)
    return scrubbed


def configure_logging(
    *, level: str = "INFO", json_output: bool = True, service: str = "api"
) -> None:
    logging.basicConfig(
        format="%(message)s", stream=sys.stdout, level=getattr(logging, level.upper(), 20)
    )
    for noisy in ("uvicorn.access", "botocore", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _inject_context,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _redact_processor,
    ]
    renderer = (
        structlog.processors.JSONRenderer() if json_output else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), 20)),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.bind_contextvars(service=service)


def get_logger(name: str) -> Any:
    """Bind the module name explicitly: PrintLoggerFactory has no stdlib logger name."""
    return structlog.get_logger().bind(logger=name)
