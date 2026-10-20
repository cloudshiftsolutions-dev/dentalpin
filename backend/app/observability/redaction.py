"""Redaction applied inside the process, before a record is written or exported."""

from __future__ import annotations

import re
from typing import Any

from app.core.log_context import _OPAQUE_SEGMENT

SENSITIVE_KEYS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "client_secret",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "jwt",
        "authorization",
        "cookie",
        "set-cookie",
        "api_key",
        "apikey",
        "x-api-key",
        "otp",
        "pin",
        "upi_pin",
        "cvv",
        "card_number",
        "private_key",
        "session",
        "aadhaar",
        "pan_number",
        "account_number",
    }
)

REDACTED = "[REDACTED]"

_EMAIL = re.compile(r"\b([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)\b")
# International numbers only (leading "+"): bare digit runs are dates, ids and
# amounts far more often than phone numbers.
_PHONE = re.compile(r"\+\d[\d ()-]{6,}\d")


def mask_phone(match: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    return f"+{digits[:2]}{'*' * max(len(digits) - 4, 1)}{digits[-2:]}"


def scrub_text(text: str) -> str:
    """Mask email addresses and international phone numbers in free text."""
    text = _EMAIL.sub(r"\1***@\2", text)
    return _PHONE.sub(mask_phone, text)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: REDACTED if str(k).lower() in SENSITIVE_KEYS else redact(v) for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return scrub_text(value)
    return value


def scrub_path(path: str) -> str:
    """Replace UUIDs and long opaque tokens in a URL path; drop the query string."""
    return _OPAQUE_SEGMENT.sub("/[id]", path.split("?", 1)[0])
