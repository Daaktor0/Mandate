"""Structured worker logging and trace-context helpers."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator, Mapping, MutableMapping
from contextlib import contextmanager
from typing import Any, cast
from uuid import uuid4

import structlog
from structlog.contextvars import bind_contextvars, bound_contextvars, clear_contextvars

SYSTEM_TRACE_ID = "system"
TRACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
REDACTED = "[REDACTED]"
REDACTED_BINARY = "[REDACTED_BINARY]"

_SAFE_LOG_KEYS = {
    "adapterbackends",
    "attempt",
    "cost",
    "currency",
    "demomode",
    "durationms",
    "errorclass",
    "errorcode",
    "event",
    "failurestate",
    "fixturerevision",
    "httppath",
    "jobid",
    "level",
    "model",
    "modelpromptversion",
    "overriddenselectors",
    "promptversion",
    "provider",
    "queuemessageid",
    "readcount",
    "reportrequestid",
    "service",
    "stage",
    "status",
    "timestamp",
    "tokencount",
    "traceid",
    "userid",
    "validationerrorcount",
    "version",
    "zerospend",
}
_SENSITIVE_EXACT_KEYS = {
    "body",
    "content",
    "cookie",
    "data",
    "details",
    "email",
    "error",
    "exception",
    "firm",
    "fullname",
    "letterhead",
    "message",
    "name",
    "password",
    "payload",
    "phone",
    "prompt",
    "raw",
    "stack",
    "text",
    "traceback",
}


def _normalise_key(key: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _is_sensitive_key(key: object) -> bool:
    normalised = _normalise_key(key)
    if normalised in _SAFE_LOG_KEYS:
        return False
    if normalised in _SENSITIVE_EXACT_KEYS:
        return True
    if normalised.endswith(("apikey", "password", "secret", "token")):
        return True
    return any(
        fragment in normalised
        for fragment in (
            "authorization",
            "billing",
            "confidential",
            "credential",
            "letterhead",
            "oauth",
            "payment",
            "prompt",
            "setcookie",
            "useradded",
            "webhooksignature",
            "workproduct",
        )
    )


def _redact_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED if _is_sensitive_key(key) else _redact_value(child)
            for key, child in value.items()
        }
    if isinstance(value, list | tuple):
        return [_redact_value(child) for child in value]
    if isinstance(value, bytes | bytearray | memoryview):
        return REDACTED_BINARY
    return value


def redact_sensitive_fields(
    _logger: object,
    _method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """Remove secret, identity, work-product and raw-content fields at the sink."""

    redacted = _redact_value(event_dict)
    if not isinstance(redacted, Mapping):  # pragma: no cover - processor contract guard
        raise TypeError("structured log event must be a mapping")
    event_dict.clear()
    event_dict.update(redacted)
    return event_dict


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
            redact_sensitive_fields,
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
