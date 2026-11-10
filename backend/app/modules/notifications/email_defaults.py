"""Built-in subjects, editable email types and preview sample data.

Only notification types delivered through the gateway are editable:
those are the ones whose clinic override is looked up at send time.
Staff emails sent straight through ``EmailService`` (AI morning digest,
VeriFactu alerts) always use the built-in files.
"""

from __future__ import annotations

from typing import Any

EDITABLE_EMAIL_TYPES: tuple[str, ...] = (
    "appointment_confirmation",
    "appointment_reminder",
    "appointment_cancelled",
    "budget_sent",
    "budget_accepted",
    "budget_reminder",
    "invoice_sent",
    "recall_reminder",
    "welcome",
)

DEFAULT_SUBJECTS: dict[str, str] = {
    "appointment_confirmation": (
        "Appointment confirmed – {{ appointment_date }} at {{ appointment_time }}"
    ),
    "appointment_reminder": (
        "Reminder: your appointment on {{ appointment_date }} at {{ appointment_time }}"
    ),
    "appointment_cancelled": "Your appointment on {{ appointment_date }} has been cancelled",
    "budget_sent": "Your treatment quote {{ budget_number }} from {{ clinic_name }}",
    "budget_accepted": "Thank you – quote {{ budget_number }} accepted",
    "budget_reminder": "Reminder: your treatment quote {{ budget_number }}",
    "invoice_sent": "Invoice {{ invoice_number }} from {{ clinic_name }}",
    "recall_reminder": "Time for your next visit at {{ clinic_name }}",
    "welcome": "Welcome to {{ clinic_name }}",
}

# Inserted as ``{{ name | money }}`` by the editor.
MONEY_FIELDS: frozenset[str] = frozenset(
    {"total", "subtotal", "discount_amount", "total_discount", "total_tax", "balance_due"}
)

# Always available: shared by every email through the layout.
COMMON_FIELDS: tuple[str, ...] = ("patient_name", "clinic_name", "clinic_phone")

_SAMPLE: dict[str, Any] = {
    "patient_name": "Priya Raman",
    "appointment_date": "12/11/2026",
    "appointment_time": "10:30",
    "professional_name": "Dr. Arun Kumar",
    "cancellation_reason": "The doctor is unavailable on this day.",
    "budget_number": "PRES-2026-0019",
    "budget_date": "10/11/2026",
    "treatments": [
        {"name": "Root canal treatment", "tooth": 36, "price": 6500.0},
        {"name": "Ceramic crown", "tooth": 36, "price": 9500.0},
    ],
    "subtotal": 16000.0,
    "discount_amount": 1000.0,
    "total": 15000.0,
    "validity_days": 30,
    "valid_until": "10/12/2026",
    "accepted_date": "10/11/2026",
    "public_url": "https://example.com/p/budget/sample",
    "notes": None,
    "custom_message": None,
    "invoice_number": "FAC-2026-0010",
    "invoice_date": "10/11/2026",
    "due_date": "25/11/2026",
    "items": [
        {
            "description": "Root canal treatment",
            "quantity": 1,
            "unit_price": 6500.0,
            "line_total": 6500.0,
        },
        {"description": "Ceramic crown", "quantity": 1, "unit_price": 9500.0, "line_total": 9500.0},
    ],
    "total_discount": 1000.0,
    "total_tax": None,
    "balance_due": 15000.0,
    "due_month": "December 2026",
    "reason": "Six-monthly check-up and cleaning",
}


def default_subject(template_key: str) -> str | None:
    return DEFAULT_SUBJECTS.get(template_key)


def sample_context(clinic: Any | None) -> dict[str, Any]:
    """Realistic preview data, branded with the clinic's own details."""
    from app.core.utils.currency import DEFAULT_CURRENCY

    return {
        **_SAMPLE,
        "clinic_name": getattr(clinic, "name", None) or "DentalPin",
        "clinic_phone": getattr(clinic, "phone", None),
        "clinic_address": getattr(clinic, "address", None),
        "currency": getattr(clinic, "currency", None) or DEFAULT_CURRENCY,
    }
