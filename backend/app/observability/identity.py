"""Service identity shared by log records and the OTel resource."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Identity:
    application: str
    service: str
    environment: str
    version: str
    revision: str | None


@lru_cache
def identity() -> Identity:
    from app.config import settings

    return Identity(
        application=os.getenv("APP_NAME") or "dentalpin",
        service=os.getenv("OTEL_SERVICE_NAME") or "dentalpin-api",
        environment=os.getenv("APP_ENV") or settings.ENVIRONMENT,
        version=os.getenv("APP_VERSION") or "unknown",
        revision=os.getenv("APP_REVISION") or None,
    )
