"""SMTP sending through a clinic's own mail server (production errors 2 Nov 2026).

* The global ``EMAIL_FROM_ADDRESS`` was stamped onto messages that then
  went through the clinic's Zoho SMTP, which refuses to relay for a
  sender the login doesn't own.
* The rejection was hidden: the server dropped the connection, and the
  ``quit()`` in ``finally`` raised "please run connect() first" instead.
"""

from __future__ import annotations

import smtplib
from uuid import uuid4

import pytest

from app.core.email.providers.base import EmailMessage, EmailResult, EmailStatus
from app.core.email.providers.smtp import SMTPProvider
from app.core.email.service import EmailService


class _RefusingServer:
    """Accepts the login, refuses the sender, then has hung up."""

    def __init__(self, *args, **kwargs) -> None:
        self.sent_from: str | None = None

    def login(self, user: str, password: str) -> None:
        pass

    def sendmail(self, from_addr: str, to_addrs: list[str], msg: str) -> None:
        self.sent_from = from_addr
        raise smtplib.SMTPSenderRefused(553, b"Sender is not allowed to relay emails", from_addr)

    def quit(self) -> None:
        raise smtplib.SMTPServerDisconnected("please run connect() first")

    def close(self) -> None:
        pass


def _provider() -> SMTPProvider:
    return SMTPProvider(
        host="smtppro.zoho.in",
        port=465,
        username="hello@cloudshiftsolutions.in",
        password="secret",
        use_ssl=True,
        default_from_email="hello@cloudshiftsolutions.in",
    )


def test_sender_refusal_is_reported_not_masked(monkeypatch) -> None:
    monkeypatch.setattr(smtplib, "SMTP_SSL", _RefusingServer)
    message = EmailMessage(
        to_email="patient@example.com",
        subject="Invoice",
        body_html="<p>hi</p>",
        from_email="noreply@dentalpin.com",
    )

    result = _provider()._send_sync(message)

    assert result.status == EmailStatus.FAILED
    assert "noreply@dentalpin.com refused" in (result.error_message or "")
    assert "connect()" not in (result.error_message or "")


class _CapturingProvider:
    name = "capture"

    def __init__(self) -> None:
        self.message: EmailMessage | None = None

    async def send(self, message: EmailMessage) -> EmailResult:
        self.message = message
        return EmailResult(status=EmailStatus.SUCCESS, provider=self.name)


@pytest.mark.asyncio
async def test_clinic_provider_keeps_its_own_sender(monkeypatch) -> None:
    service = EmailService()
    clinic_provider = _CapturingProvider()

    async def fake_create(db, clinic_id):
        return clinic_provider

    monkeypatch.setattr(service, "create_provider_for_clinic", fake_create)

    await service.send(
        EmailMessage(to_email="patient@example.com", subject="Invoice", body_html="<p>hi</p>"),
        db=object(),
        clinic_id=uuid4(),
    )

    assert clinic_provider.message is not None
    # Left empty so the clinic provider fills in its configured address.
    assert clinic_provider.message.from_email is None
