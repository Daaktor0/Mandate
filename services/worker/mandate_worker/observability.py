"""Structured worker logging and trace-context helpers."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from typing import Any, cast
from uuid import uuid4

import structlog
from structlog.contextvars import bind_contextvars, bound_contextvars, clear_contextvars

SYSTEM_TRACE_ID = "system"
TRACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


def normalise_trace_id(candidate: str | None) -> str:
    """Accept a bounded trace ID or mint a safe one."""

    if candidate is not None and TRACE_ID_PATTERN.fullmatch(candidate):
        return candidate
    return uuid4().hex


def ensure_trace_id(
    _logger: object,
    _method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """Make the trace field structural rather than caller-dependent."""

    event_dict.setdefault("trace_id", SYSTEM_TRACE_ID)
    return event_dict


def configure_logging(*, level: int = logging.INFO) -> None:
    """Configure one-line JSON logs suitable for container collection."""

    logging.basicConfig(level=level, format="%(message)s", force=True)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            ensure_trace_id,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(sort_keys=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger() -> structlog.stdlib.BoundLogger:
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger("mandate_worker"))


@contextmanager
def trace_context(trace_id: str, **context: object) -> Iterator[None]:
    """Bind trace-safe audit fields for the duration of one operation."""

    clear_contextvars()
    bind_contextvars(trace_id=trace_id)
    with bound_contextvars(**context):
        yield
    clear_contextvars()
