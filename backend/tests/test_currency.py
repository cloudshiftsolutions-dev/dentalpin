"""Currency: helper + clinic-level setting + cross-module inheritance."""

from decimal import Decimal

import pytest
from httpx import AsyncClient
from jinja2 import Environment
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.core.email.service import _money_filter
from app.core.utils.currency import format_currency, money_locale

# ---------------------------------------------------------------------------
# Helper: babel-backed format_currency
# ---------------------------------------------------------------------------


def test_format_currency_eur_es() -> None:
    out = format_currency(Decimal("1234.56"), "EUR", locale="es_ES")
    # Babel renders es_ES EUR with comma decimal + non-breaking space + €.
    assert "1234" in out.replace(".", "") or "1.234" in out
    assert "€" in out


def test_format_currency_usd_en() -> None:
    out = format_currency(Decimal("1234.56"), "USD", locale="en_US")
    assert out == "$1,234.56"


def test_format_currency_locale_dash_normalized() -> None:
    """``en-US`` (BCP 47) is accepted and normalized to ``en_US``."""
    out = format_currency(100, "USD", locale="en-US")
    assert out == "$100.00"


def test_format_currency_defaults_to_rupees_with_indian_grouping() -> None:
    assert format_currency(Decimal("164000")) == "₹1,64,000.00"
    assert format_currency(500, None) == "₹500.00"


@pytest.mark.parametrize("lang_locale", ["en_US", "es_ES", "de_DE", None])
def test_money_locale_uses_indian_grouping_for_rupees(lang_locale: str | None) -> None:
    assert money_locale(lang_locale, "INR") == "en_IN"


def test_money_locale_keeps_ui_locale_for_other_currencies() -> None:
    assert money_locale("es_ES", "EUR") == "es_ES"
    assert money_locale(None, "EUR") == "en_IN"


def test_email_money_filter_uses_context_currency() -> None:
    env = Environment(autoescape=False)
    env.filters["money"] = _money_filter
    template = env.from_string("{{ total | money }}")
    assert template.render(total=16400.0, currency="INR", locale="en") == "₹16,400.00"
    assert template.render(total=16400.0, locale="ta") == "₹16,400.00"
    assert template.render(total=10, currency="USD", locale="en") == "$10.00"
    assert template.render(total=None, currency="INR") == ""


# ---------------------------------------------------------------------------
# Clinic currency PUT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clinic_currency_default_is_eur(
    db_session: AsyncSession, test_clinic: Clinic
) -> None:
    await db_session.refresh(test_clinic)
    assert test_clinic.currency == "EUR"


@pytest.mark.asyncio
async def test_update_clinic_currency_persists(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_clinic: Clinic,
    db_session: AsyncSession,
) -> None:
    response = await client.put(
        "/api/v1/auth/clinics",
        json={"currency": "USD"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["data"]["currency"] == "USD"

    db_session.expire_all()
    await db_session.refresh(test_clinic)
    assert test_clinic.currency == "USD"


@pytest.mark.asyncio
async def test_update_clinic_currency_rejects_invalid_iso(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_clinic: Clinic,
) -> None:
    response = await client.put(
        "/api/v1/auth/clinics",
        json={"currency": "euro"},  # not 3 uppercase letters
        headers=auth_headers,
    )
    assert response.status_code == 422
