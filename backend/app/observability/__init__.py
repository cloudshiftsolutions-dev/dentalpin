"""CloudShift observability: JSON logs plus OpenTelemetry export to OpenObserve.

Driven entirely by env vars (``APP_*``, ``LOG_*``, ``OTEL_*``). Without
``OTEL_EXPORTER_OTLP_ENDPOINT`` the backend still logs JSON to stdout and
exports nothing, so local runs and upstream-style deploys are unaffected.
Patient data never leaves the process: logs are redacted before they are
written or exported, and span URLs are scrubbed of ids and query strings.
"""

from .context import bind_fields, current_trace_id, report_error, set_span_identity
from .jobs import job_run, traced_job
from .logging import setup_logging
from .telemetry import instrument_app, setup_telemetry, shutdown_telemetry

__all__ = [
    "bind_fields",
    "current_trace_id",
    "instrument_app",
    "job_run",
    "report_error",
    "set_span_identity",
    "setup_logging",
    "setup_telemetry",
    "shutdown_telemetry",
    "traced_job",
]
