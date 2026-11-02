"""DENTALPIN-13: recall intervals shorter than a month (days / weeks)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.modules.patients.models import Patient
from app.modules.recalls.schemas import RecallSettingsUpdate
from app.modules.recalls.service import interval_due

# --- Pure date math -----------------------------------------------------------


def test_month_interval_keeps_monthly_bucket() -> None:
    assert interval_due(date(2026, 11, 2), 6, "month") == (date(2027, 5, 1), None)


def test_week_interval_pins_exact_date() -> None:
    assert interval_due(date(2026, 11, 2), 2, "week") == (date(2026, 11, 1), date(2026, 11, 16))


def test_day_interval_rolls_into_next_month() -> None:
    assert interval_due(date(2026, 11, 25), 10, "day") == (date(2026, 12, 1), date(2026, 12, 5))


# --- Settings validation ------------------------------------------------------


def test_settings_accept_short_intervals() -> None:
    update = RecallSettingsUpdate(
        reason_intervals={"post_op": 10, "ortho_review": 2},
        reason_interval_units={"post_op": "day", "ortho_review": "week"},
    )
    assert update.reason_interval_units == {"post_op": "day", "ortho_review": "week"}


@pytest.mark.parametrize(
    ("value", "unit"),
    [(61, "month"), (105, "week"), (731, "day"), (-1, "day")],
)
def test_settings_reject_out_of_range_intervals(value: int, unit: str) -> None:
    with pytest.raises(ValidationError):
        RecallSettingsUpdate(
            reason_intervals={"post_op": value},
            reason_interval_units={"post_op": unit},
        )


def test_settings_reject_unknown_unit() -> None:
    with pytest.raises(ValidationError):
        RecallSettingsUpdate(reason_interval_units={"post_op": "fortnight"})


# --- API ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_settings_round_trip_units_and_legacy_months(
    client: AsyncClient, auth_headers: dict
) -> None:
    res = await client.get("/api/v1/recalls/settings", headers=auth_headers)
    settings = res.json()["data"]
    # Existing settings have no units: every interval still reads as months.
    assert settings["reason_interval_units"] == {}

    update = await client.put(
        "/api/v1/recalls/settings",
        json={
            "reason_intervals": {**settings["reason_intervals"], "post_op": 10},
            "reason_interval_units": {"post_op": "day"},
        },
        headers=auth_headers,
    )
    assert update.status_code == 200, update.text
    data = update.json()["data"]
    assert data["reason_intervals"]["post_op"] == 10
    assert data["reason_interval_units"] == {"post_op": "day"}
    assert data["reason_intervals"]["hygiene"] == 6


@pytest.mark.asyncio
async def test_suggestion_uses_week_interval(
    client: AsyncClient, auth_headers: dict, test_patient: Patient
) -> None:
    settings = (await client.get("/api/v1/recalls/settings", headers=auth_headers)).json()["data"]
    await client.put(
        "/api/v1/recalls/settings",
        json={
            "reason_intervals": {**settings["reason_intervals"], "hygiene": 2},
            "reason_interval_units": {"hygiene": "week"},
        },
        headers=auth_headers,
    )
    res = await client.get(
        f"/api/v1/recalls/suggestions/next?patient_id={test_patient.id}"
        "&treatment_category_key=preventivo",
        headers=auth_headers,
    )
    suggestion = res.json()["data"]
    expected = date.today() + timedelta(days=14)
    assert suggestion["interval_value"] == 2
    assert suggestion["interval_unit"] == "week"
    assert suggestion["interval_months"] == 0
    assert suggestion["due_date"] == expected.isoformat()
    assert suggestion["due_month"] == expected.replace(day=1).isoformat()


@pytest.mark.asyncio
async def test_exact_due_date_decides_the_month(
    client: AsyncClient, auth_headers: dict, test_patient: Patient
) -> None:
    res = await client.post(
        "/api/v1/recalls/",
        json={
            "patient_id": str(test_patient.id),
            "due_month": "2026-12-01",
            "due_date": "2026-11-16",
            "reason": "post_op",
        },
        headers=auth_headers,
    )
    assert res.status_code == 201, res.text
    recall = res.json()["data"]
    assert recall["due_date"] == "2026-11-16"
    assert recall["due_month"] == "2026-11-01"


@pytest.mark.asyncio
async def test_snooze_moves_exact_due_date(
    client: AsyncClient, auth_headers: dict, test_patient: Patient
) -> None:
    created = await client.post(
        "/api/v1/recalls/",
        json={
            "patient_id": str(test_patient.id),
            "due_month": "2027-01-01",
            "due_date": "2027-01-31",
            "reason": "post_op",
        },
        headers=auth_headers,
    )
    recall_id = created.json()["data"]["id"]
    res = await client.post(
        f"/api/v1/recalls/{recall_id}/snooze", json={"months": 1}, headers=auth_headers
    )
    assert res.status_code == 200, res.text
    recall = res.json()["data"]
    assert recall["due_month"] == "2027-02-01"
    assert recall["due_date"] == "2027-02-28"
