"""OpenTelemetry providers and instrumentation, exporting OTLP to OpenObserve.

Off unless ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set. Exporters read the
standard ``OTEL_EXPORTER_OTLP_*`` env vars (endpoint, headers, protocol);
the sampler reads ``OTEL_TRACES_SAMPLER`` / ``_ARG``. Never raises: a
telemetry problem must not stop the backend from booting.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import FastAPI

from .identity import identity
from .redaction import scrub_path, scrub_text

logger = logging.getLogger(__name__)

_providers: list[Any] = []

# URL and client attributes the ASGI/httpx instrumentations record, old and
# stable semantic conventions. The path keeps its shape but loses ids and
# tokens (``/public/budgets/{token}``, ``?t=...``); client IPs are dropped.
_URL_KEYS = ("http.target", "url.path")
_FULL_URL_KEYS = ("http.url", "url.full")
_DROP_KEYS = ("url.query", "http.client_ip", "net.peer.ip", "client.address", "client.port")


def enabled() -> bool:
    return bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"))


def _scrub_span(span, url: str | None = None) -> None:
    if not span.is_recording():
        return
    attrs = getattr(span, "attributes", None) or {}
    for key in _URL_KEYS:
        if key in attrs:
            span.set_attribute(key, scrub_path(str(attrs[key])))
    for key in _FULL_URL_KEYS:
        if key in attrs or (url and key == "url.full"):
            span.set_attribute(key, scrub_path(str(url or attrs[key])))
    for key in _DROP_KEYS:
        if key in attrs:
            span.set_attribute(key, "")


def _scrub_value(value: Any) -> Any:
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, tuple | list):
        return type(value)(scrub_text(v) if isinstance(v, str) else v for v in value)
    return value


def scrub_finished_span(span):
    """Copy of a finished span with free text masked.

    Exception events carry the raw exception message and stack trace, and
    database errors quote row values (``Key (email)=(...)``), so attributes,
    event attributes and the status description are scrubbed before export.
    """
    from opentelemetry.sdk.trace import Event, ReadableSpan
    from opentelemetry.trace import Status

    def clean(attrs):
        return {k: _scrub_value(v) for k, v in (attrs or {}).items()}

    status = span.status
    if status.description:
        status = Status(status.status_code, scrub_text(status.description))
    return ReadableSpan(
        name=span.name,
        context=span.context,
        parent=span.parent,
        resource=span.resource,
        attributes=clean(span.attributes),
        events=[Event(e.name, clean(e.attributes), e.timestamp) for e in span.events],
        links=span.links,
        kind=span.kind,
        status=status,
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )


class ScrubbingSpanExporter:
    """Wraps the OTLP exporter so no span leaves the process unscrubbed."""

    def __init__(self, inner) -> None:
        self._inner = inner

    def export(self, spans):
        return self._inner.export([scrub_finished_span(s) for s in spans])

    def shutdown(self) -> None:
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._inner.force_flush(timeout_millis)


def _server_request_hook(span, scope: dict) -> None:
    _scrub_span(span)


def _client_request_hook(span, request) -> None:
    _scrub_span(span, str(getattr(request, "url", "")) or None)


async def _async_client_request_hook(span, request) -> None:
    _client_request_hook(span, request)


def setup_telemetry() -> bool:
    """Register trace, log and metric providers. Returns True when exporting."""
    if _providers or not enabled():
        return bool(_providers)
    try:
        from opentelemetry import metrics, trace
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from opentelemetry.sdk._logs import LoggerProvider
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        from app.database import engine

        who = identity()
        attributes = {
            "service.name": who.service,
            "service.namespace": who.application,
            "service.version": who.version,
            "deployment.environment.name": who.environment,
        }
        if who.revision:
            attributes["vcs.ref.head.revision"] = who.revision
        resource = Resource.create(attributes)

        tracer_provider = TracerProvider(resource=resource)
        tracer_provider.add_span_processor(
            BatchSpanProcessor(ScrubbingSpanExporter(OTLPSpanExporter()))
        )
        trace.set_tracer_provider(tracer_provider)

        logger_provider = LoggerProvider(resource=resource)
        logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
        set_logger_provider(logger_provider)

        meter_provider = MeterProvider(
            resource=resource,
            metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter())],
        )
        metrics.set_meter_provider(meter_provider)

        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
        HTTPXClientInstrumentor().instrument(
            request_hook=_client_request_hook,
            async_request_hook=_async_client_request_hook,
        )
        _providers.extend([tracer_provider, logger_provider, meter_provider])
    except Exception:
        logger.exception("OpenTelemetry setup failed; exporting nothing")
        return False
    logger.info("Telemetry export enabled", extra={"event": "telemetry.enabled"})
    return True


def instrument_app(app: FastAPI) -> None:
    """Trace every request except health probes. Call after the middleware is added."""
    if not _providers:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(
            app,
            excluded_urls="health",
            server_request_hook=_server_request_hook,
            exclude_spans=["receive", "send"],
        )
    except Exception:
        logger.exception("FastAPI instrumentation failed; requests are not traced")


def shutdown_telemetry() -> None:
    """Flush buffered spans, logs and metrics before the process exits."""
    while _providers:
        provider = _providers.pop()
        try:
            provider.shutdown()
        except Exception:
            pass
