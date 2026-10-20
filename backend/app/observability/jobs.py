"""Scheduled-job runs: one span, a duration metric and one ERROR on failure.

Jobs run as often as every 45 seconds, so a successful run logs at DEBUG
(off in production) and is visible through its span and metrics; a
failure is always reported. Failures are swallowed after reporting so
APScheduler doesn't log the same exception a second time.
"""

from __future__ import annotations

import contextlib
import functools
import inspect
import logging
import time
from collections.abc import Callable, Iterator
from typing import Any
from uuid import uuid4

from opentelemetry import metrics, trace

from app.core.log_context import bind

from .context import bind_fields, report_error

logger = logging.getLogger("app.jobs")
_tracer = trace.get_tracer("dentalpin.jobs")
_meter = metrics.get_meter("dentalpin.jobs")
_duration = _meter.create_histogram(
    "job_duration_seconds", unit="s", description="Scheduled job run time"
)
_failures = _meter.create_counter("job_failures_total", description="Scheduled job failures")


@contextlib.contextmanager
def job_run(job_id: str) -> Iterator[None]:
    start = time.perf_counter()
    with (
        _tracer.start_as_current_span(
            f"job {job_id}", attributes={"job": job_id}, record_exception=False
        ),
        bind(request_id=f"job_{uuid4().hex[:16]}"),
        bind_fields(job=job_id),
    ):
        try:
            yield
        except Exception as exc:
            elapsed = time.perf_counter() - start
            _failures.add(1, {"job": job_id})
            report_error(
                exc,
                "Scheduled job failed",
                log=logger,
                event="job.failed",
                duration_ms=round(elapsed * 1000),
            )
        else:
            elapsed = time.perf_counter() - start
            logger.debug(
                "Scheduled job succeeded",
                extra={"event": "job.succeeded", "duration_ms": round(elapsed * 1000)},
            )
        _duration.record(elapsed, {"job": job_id})


def traced_job(job_id: str, func: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a scheduler callable (sync or async) in :func:`job_run`."""
    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def run_async(*args: Any, **kwargs: Any) -> Any:
            with job_run(job_id):
                return await func(*args, **kwargs)
            return None

        return run_async

    @functools.wraps(func)
    def run_sync(*args: Any, **kwargs: Any) -> Any:
        with job_run(job_id):
            return func(*args, **kwargs)
        return None

    return run_sync
