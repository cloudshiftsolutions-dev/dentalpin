"""Correlation fields, span identity and the single error-reporting path."""

from __future__ import annotations

import contextlib
import logging
import re
from collections.abc import Iterator
from contextvars import ContextVar, Token
from typing import Any
from uuid import UUID, uuid4

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

logger = logging.getLogger("app.observability")

_SAFE_ID = re.compile(r"^[A-Za-z0-9_\-:.]{1,128}$")

# Extra low-cardinality fields (correlation_id, job, ...) merged into every
# log record emitted in this context. request_id / clinic / user live in
# app.core.log_context, which upstream code already binds.
FIELDS: ContextVar[dict[str, Any] | None] = ContextVar("log_fields", default=None)


def is_safe_id(value: str | None) -> bool:
    """An inbound id is accepted only if it can't inject into logs."""
    return bool(value and _SAFE_ID.match(value))


def safe_id(value: str | None, prefix: str) -> str:
    return value if value and is_safe_id(value) else f"{prefix}_{uuid4().hex}"


def get_fields() -> dict[str, Any]:
    return FIELDS.get() or {}


def set_fields(**fields: Any) -> Token:
    return FIELDS.set({**get_fields(), **fields})


@contextlib.contextmanager
def bind_fields(**fields: Any) -> Iterator[None]:
    token = set_fields(**fields)
    try:
        yield
    finally:
        FIELDS.reset(token)


def set_span_identity(*, tenant_id: str | UUID | None, user_id: str | UUID | None) -> None:
    span = trace.get_current_span()
    if tenant_id is not None:
        span.set_attribute("tenant_id", str(tenant_id))
    if user_id is not None:
        span.set_attribute("user_id", str(user_id))


def current_trace_id() -> str | None:
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else None


def report_error(
    exc: BaseException, message: str, *, log: logging.Logger | None = None, **fields: Any
) -> None:
    """Report a failure exactly once: ERROR log with error.* fields, plus the
    exception and ERROR status on the active span."""
    span = trace.get_current_span()
    span.record_exception(exc)
    span.set_status(Status(StatusCode.ERROR, message))
    (log or logger).error(message, exc_info=exc, extra=fields)
