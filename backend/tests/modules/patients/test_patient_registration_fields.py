"""patients registration: phone validation, gender + address on create."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.core.auth.models import Clinic
from app.modules.patients.schemas import PatientCreate, PatientExtendedUpdate, PatientUpdate
from app.modules.patients.tools import CreatePatientArgs, UpdatePatientArgs


@pytest.mark.parametrize(
    "phone",
    ["+91 98765 43210", "9876543210", "+1 (212) 555-0001", "044-2434.5678", "  98765 43210  "],
)
def test_phone_accepts_real_world_formats(phone: str) -> None:
    patient = PatientCreate(first_name="Meena", last_name="Raman", phone=phone)
    assert patient.phone == phone.strip()


@pytest.mark.parametrize(
    "phone", ["abcdefghij", "98765abcde", "call me", "+91 98765 4321O", "12345"]
)
def test_phone_rejects_letters_and_short_numbers(phone: str) -> None:
    with pytest.raises(ValidationError):
        PatientCreate(first_name="Meena", last_name="Raman", phone=phone)


def test_phone_blank_becomes_none() -> None:
    assert PatientCreate(first_name="Meena", last_name="Raman", phone="   ").phone is None


@pytest.mark.parametrize("schema", [PatientUpdate, PatientExtendedUpdate])
def test_phone_rule_applies_to_updates(schema: type) -> None:
    with pytest.raises(ValidationError):
        schema(phone="98765abcde")
    assert schema(phone="+91 98765 43210").phone == "+91 98765 43210"


@pytest.mark.parametrize("schema", [CreatePatientArgs, UpdatePatientArgs])
def test_phone_rule_applies_to_agent_tools(schema: type) -> None:
    base = (
        {"first_name": "Meena", "last_name": "Raman"}
        if schema is CreatePatientArgs
        else {"patient_id": "00000000-0000-0000-0000-000000000001"}
    )
    with pytest.raises(ValidationError):
        schema(**base, phone="not a number")


def test_gender_must_be_a_known_value() -> None:
    assert PatientCreate(first_name="A", last_name="B", gender="female").gender == "female"
    with pytest.raises(ValidationError):
        PatientCreate(first_name="A", last_name="B", gender="F")


@pytest.mark.asyncio
async def test_create_patient_saves_gender_and_address(
    client: AsyncClient, auth_headers: dict, test_clinic: Clinic
) -> None:
    response = await client.post(
        "/api/v1/patients",
        headers=auth_headers,
        json={
            "first_name": "Aravind",
            "last_name": "Selvam",
            "phone": "+91 98765 43210",
            "gender": "male",
            "date_of_birth": "1990-05-01",
            "address": {
                "street": "12 Gandhi Road",
                "city": "Coimbatore",
                "postal_code": "641001",
                "province": "Tamil Nadu",
                "country": "IN",
            },
        },
    )
    assert response.status_code == 201, response.text
    patient_id = response.json()["data"]["id"]

    detail = await client.get(f"/api/v1/patients/{patient_id}/extended", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    data = detail.json()["data"]
    assert data["gender"] == "male"
    assert data["phone"] == "+91 98765 43210"
    assert data["address"]["city"] == "Coimbatore"
    assert data["address"]["country"] == "IN"


@pytest.mark.asyncio
async def test_create_patient_rejects_letters_in_phone(
    client: AsyncClient, auth_headers: dict, test_clinic: Clinic
) -> None:
    response = await client.post(
        "/api/v1/patients",
        headers=auth_headers,
        json={"first_name": "Aravind", "last_name": "Selvam", "phone": "98765abcde"},
    )
    assert response.status_code == 422
