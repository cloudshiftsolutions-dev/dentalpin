"""invoice.sent → notification context (production error 2 Nov 2026).

``Invoice.balance_due`` stopped being a column when paid totals moved to
``compute_paid_summary``; the handler still read the attribute, so every
emailed / WhatsApp'd invoice raised AttributeError and queued nothing.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.modules.billing.models import Invoice
from app.modules.notifications.gateway import NotificationGateway
from app.modules.notifications.handlers import NotificationHandlers
from app.modules.patients.models import Patient


@pytest.mark.asyncio
async def test_invoice_sent_queues_with_computed_balance(
    db_session: AsyncSession, test_clinic: Clinic, test_patient: Patient, monkeypatch
) -> None:
    test_patient.email = "patient@example.com"
    invoice = Invoice(
        id=uuid4(),
        clinic_id=test_clinic.id,
        patient_id=test_patient.id,
        invoice_number="FAC-2026-0099",
        status="issued",
        issue_date=date(2026, 11, 2),
        billing_name="Aravind Selvam",
        subtotal=Decimal("1500.00"),
        total_discount=Decimal("0.00"),
        total_tax=Decimal("0.00"),
        total=Decimal("1500.00"),
    )
    db_session.add(invoice)
    await db_session.flush()

    queued: list[dict] = []

    async def fake_enqueue(**kwargs):
        queued.append(kwargs)

    monkeypatch.setattr(NotificationGateway, "enqueue", staticmethod(fake_enqueue))

    await NotificationHandlers.on_invoice_sent(
        {
            "clinic_id": str(test_clinic.id),
            "invoice_id": str(invoice.id),
            "send_method": "email",
        },
        db=db_session,
    )

    assert len(queued) == 1
    context = queued[0]["context"]
    # No payments yet: the whole total is still due.
    assert context["balance_due"] == 1500.0
    assert context["invoice_number"] == "FAC-2026-0099"
    assert queued[0]["channels"] == ["email"]
