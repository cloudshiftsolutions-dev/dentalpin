"""JSON log records in the CloudShift contract, on stdout and over OTLP.

Upstream DentalPin logs through stdlib ``logging`` with %-style messages;
this keeps every call site as is and changes only how records are
rendered. The same redacted record is written to stdout and handed to the
OTel logs SDK (a no-op until ``setup_telemetry`` registers a provider), so
nothing unredacted is ever exported.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace
from opentelemetry._logs import SeverityNumber
from opentelemetry._logs import get_logger as get_otel_logger

from app.core.log_context import CLINIC_ID, REQUEST_ID, USER_ID, LogContextFilter
from app.core.log_context import setup_logging as setup_text_logging

from .context import get_fields
from .identity import identity
from .redaction import redact, scrub_text

LEVELS = {"WARNING": "WARN", "CRITICAL": "FATAL"}
SEVERITY = {
    "DEBUG": SeverityNumber.DEBUG,
    "INFO": SeverityNumber.INFO,
    "WARN": SeverityNumber.WARN,
    "ERROR": SeverityNumber.ERROR,
    "FATAL": SeverityNumber.FATAL,
}
_RESERVED = frozenset(vars(logging.makeLogRecord({}))) | {
    "message",
    "asctime",
    "taskName",
    "request_id",
    "clinic_id",
    "user_id",
    "color_message",  # uvicorn's ANSI-coloured copy of the message
}
# Kept out of OTLP attributes: they are the record body, severity and the
# span context the SDK attaches on its own.
_NOT_ATTRIBUTES = frozenset({"message", "level", "timestamp", "trace_id", "span_id"})
_UNBOUND = "-"


def _bound(record: logging.LogRecord, name: str, var) -> str | None:
    value = getattr(record, name, None) or var.get()
    return None if value in (None, _UNBOUND) else str(value)


def _flatten(prefix: str, value: Any, out: dict[str, Any]) -> None:
    if isinstance(value, dict):
        for key, inner in value.items():
            _flatten(f"{prefix}.{key}", inner, out)
    elif value is not None:
        out[prefix] = value if isinstance(value, str | bool | int | float) else str(value)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        who = identity()
        level = LEVELS.get(record.levelname, record.levelname)
        doc: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": level,
            "message": record.getMessage(),
            "logger": record.name,
            "application": who.application,
            "service": who.service,
            "environment": who.environment,
            "version": who.version,
        }
        ctx = trace.get_current_span().get_span_context()
        if ctx.is_valid:
            doc["trace_id"] = format(ctx.trace_id, "032x")
            doc["span_id"] = format(ctx.span_id, "016x")
        for key, value in (
            ("request_id", _bound(record, "request_id", REQUEST_ID)),
            ("tenant_id", _bound(record, "clinic_id", CLINIC_ID)),
            ("user_id", _bound(record, "user_id", USER_ID)),
        ):
            if value:
                doc[key] = value
        doc.update(get_fields())
        doc.update({k: v for k, v in vars(record).items() if k not in _RESERVED})
        if record.exc_info and record.exc_info[1] is not None:
            exc_type, exc, tb = record.exc_info
            doc["error"] = {
                "type": exc_type.__name__,
                "message": str(exc),
                "stack_trace": "".join(traceback.format_exception(exc_type, exc, tb)),
            }

        doc = redact(doc)
        # The exporter's own warnings (e.g. OpenObserve unreachable) must not
        # be fed back into the exporter.
        if not record.name.startswith("opentelemetry"):
            self._export(doc, level)
        return json.dumps(doc, default=str, ensure_ascii=False)

    @staticmethod
    def _export(doc: dict[str, Any], level: str) -> None:
        attributes: dict[str, Any] = {}
        for key, value in doc.items():
            if key not in _NOT_ATTRIBUTES:
                _flatten(key, value, attributes)
        try:
            get_otel_logger(doc["service"]).emit(
                severity_text=level,
                severity_number=SEVERITY.get(level, SeverityNumber.INFO),
                body=doc["message"],
                attributes=attributes,
            )
        except Exception:  # export must never break logging
            pass


def _wants_json() -> bool:
    from app.config import settings

    default = "text" if settings.ENVIRONMENT == "development" else "json"
    return os.getenv("LOG_FORMAT", default).lower() == "json"


def setup_logging() -> None:
    """Route every logger (app, uvicorn, libraries) through one stdout handler.

    ``LOG_FORMAT=text`` (the default in development) keeps upstream's
    human-readable format. Idempotent.
    """
    level = os.getenv("LOG_LEVEL", "info").upper()
    if not _wants_json():
        setup_text_logging(level)
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(LogContextFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # The request middleware writes a structured access line instead.
    logging.getLogger("uvicorn.access").disabled = True
    # httpx logs every request with its full URL (query strings, tokens);
    # outbound calls are traced as spans with scrubbed URLs instead.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    # Two INFO lines per run for jobs firing every 45 s; each run already
    # has a span and metrics (app.observability.jobs).
    logging.getLogger("apscheduler.executors").setLevel(logging.WARNING)
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True


__all__ = ["JsonFormatter", "scrub_text", "setup_logging"]
