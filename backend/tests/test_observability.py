"""Observability: JSON log contract, redaction, access log, job reporting."""

from __future__ import annotations

import json
import logging

import pytest
from httpx import ASGITransport, AsyncClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from app.core.log_context import bind
from app.main import app
from app.observability.context import bind_fields, is_safe_id
from app.observability.jobs import job_run, traced_job
from app.observability.logging import JsonFormatter
from app.observability.redaction import redact, scrub_path, scrub_text
from app.observability.telemetry import _scrub_span, scrub_finished_span

_exporter = InMemorySpanExporter()
_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(_exporter))


@pytest.fixture
def spans():
    """Spans recorded by a local SDK provider (the global one stays untouched)."""
    original = trace._TRACER_PROVIDER
    trace._TRACER_PROVIDER = _provider
    _exporter.clear()
    yield _exporter
    trace._TRACER_PROVIDER = original


def _render(record: logging.LogRecord) -> dict:
    return json.loads(JsonFormatter().format(record))


def _record(msg: str, level: int = logging.INFO, **extra) -> logging.LogRecord:
    record = logging.LogRecord("app.test", level, __file__, 1, msg, (), None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_record_follows_log_contract() -> None:
    with (
        bind(request_id="req-1", clinic_id="clinic-9", user_id="user-3"),
        bind_fields(correlation_id="corr_1"),
    ):
        doc = _render(_record("Invoice issued", logging.WARNING, event="invoice.issued"))

    assert doc["level"] == "WARN"
    assert doc["message"] == "Invoice issued"
    assert doc["event"] == "invoice.issued"
    assert doc["timestamp"].endswith("Z")
    assert doc["request_id"] == "req-1"
    assert doc["tenant_id"] == "clinic-9"
    assert doc["user_id"] == "user-3"
    assert doc["correlation_id"] == "corr_1"
    assert {"application", "service", "environment", "version"} <= doc.keys()
    assert "clinic_id" not in doc


def test_unbound_context_is_omitted() -> None:
    doc = _render(_record("Scheduler started"))
    assert "request_id" not in doc and "tenant_id" not in doc


def test_exception_becomes_error_fields() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = _record("Job failed", logging.ERROR)
        record.exc_info = sys.exc_info()
    doc = _render(record)
    assert doc["level"] == "ERROR"
    assert doc["error"]["type"] == "ValueError"
    assert doc["error"]["message"] == "boom"
    assert "Traceback" in doc["error"]["stack_trace"]


def test_secrets_and_contact_details_are_redacted() -> None:
    doc = _render(
        _record(
            "SMTP recipients refused: {'priya@example.com': (550, b'no')} call +91 44 2341 2349",
            payload={"password": "hunter2", "nested": {"Authorization": "Bearer x"}},
        )
    )
    assert "priya@example.com" not in doc["message"]
    assert "p***@example.com" in doc["message"]
    assert "2341 2349" not in doc["message"]
    assert doc["payload"]["password"] == "[REDACTED]"
    assert doc["payload"]["nested"]["Authorization"] == "[REDACTED]"


def test_redaction_leaves_dates_and_ids_alone() -> None:
    text = "Appointment 2026-10-13 04:00 for d0eebc99-9c0b-4ef8-bb6d-6bb9bd380a40, total 5400"
    assert scrub_text(text) == text
    assert redact({"count": 3, "ok": True}) == {"count": 3, "ok": True}


def test_scrub_path_hides_ids_tokens_and_query() -> None:
    assert (
        scrub_path("/api/v1/patients/d0eebc99-9c0b-4ef8-bb6d-6bb9bd380a40/timeline?page=2")
        == "/api/v1/patients/[id]/timeline"
    )
    assert scrub_path("/api/v1/public/budgets/abcDEF123456789xyz_TOKEN") == (
        "/api/v1/public/budgets/[id]"
    )


def test_server_span_urls_are_scrubbed(spans) -> None:
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span(
        "GET /api/v1/public/budgets/{token}",
        attributes={
            "http.target": "/api/v1/public/budgets/abcDEF123456789xyz_TOKEN?t=secret",
            "url.full": "https://x.test/api/v1/public/budgets/abcDEF123456789xyz_TOKEN?t=secret",
            "client.address": "203.0.113.7",
        },
    ) as span:
        _scrub_span(span)
    attrs = spans.get_finished_spans()[0].attributes
    assert attrs["http.target"] == "/api/v1/public/budgets/[id]"
    assert "secret" not in attrs["url.full"] and "TOKEN" not in attrs["url.full"]
    assert attrs["client.address"] == ""


def test_exported_span_exceptions_are_scrubbed(spans) -> None:
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("INSERT patients") as span:
        try:
            raise ValueError("Key (email)=(priya@example.com) already exists")
        except ValueError as exc:
            span.record_exception(exc)
            span.set_status(trace.Status(StatusCode.ERROR, f"failed: {exc}"))
    cleaned = scrub_finished_span(spans.get_finished_spans()[0])
    event = cleaned.events[0].attributes
    assert "priya@example.com" not in event["exception.message"]
    assert "priya@example.com" not in event["exception.stacktrace"]
    assert "p***@example.com" in event["exception.message"]
    assert "priya@example.com" not in cleaned.status.description
    assert cleaned.status.status_code is StatusCode.ERROR
    assert cleaned.context == spans.get_finished_spans()[0].context


def test_inbound_ids_must_be_safe() -> None:
    assert is_safe_id("trace-1234")
    assert not is_safe_id("bad id\ninjected")
    assert not is_safe_id("x" * 129)


@pytest.mark.asyncio
async def test_access_line_uses_route_template(caplog) -> None:
    caplog.set_level(logging.INFO, logger="app.access")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as http:
        response = await http.get("/api/v1", headers={"X-Correlation-Id": "corr_abc"})
        health = await http.get("/health")
    assert response.headers["x-correlation-id"] == "corr_abc"
    assert len(response.headers["x-request-id"]) == 16
    assert health.headers["x-correlation-id"].startswith("corr_")

    lines = [r for r in caplog.records if r.name == "app.access"]
    assert len(lines) == 1, "health probes are not access-logged"
    assert lines[0].event == "http.request.completed"
    assert lines[0].http["route"] == "/api/v1"
    assert lines[0].http["status_code"] == 200


@pytest.mark.asyncio
async def test_failed_job_is_reported_once_and_swallowed(spans, caplog) -> None:
    caplog.set_level(logging.DEBUG, logger="app.jobs")

    async def broken() -> None:
        raise RuntimeError("outbox down")

    await traced_job("notifications_dispatch_outbox", broken)()

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1
    assert errors[0].event == "job.failed"
    span = spans.get_finished_spans()[0]
    assert span.name == "job notifications_dispatch_outbox"
    assert span.status.status_code is StatusCode.ERROR


def test_successful_sync_job_returns_value(spans, caplog) -> None:
    caplog.set_level(logging.DEBUG, logger="app.jobs")
    assert traced_job("auto_close_expired_plans", lambda: 7)() == 7
    assert [r.event for r in caplog.records if r.name == "app.jobs"] == ["job.succeeded"]
    with job_run("noop"):
        pass
    assert spans.get_finished_spans()[-1].status.status_code is StatusCode.UNSET
