"""Generated documents print patient age, gender and doctor (no DB)."""

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from app.modules.documents.pdf import _LABELS, DocumentPDFService
from app.modules.documents.schemas import DocumentCreate

EN = _LABELS["en"]
CLINIC = SimpleNamespace(
    name="Aruna Dental Hospital",
    address={"street": "12 MG Road", "city": "Chennai", "postal_code": "600001"},
    phone="",
    email="",
    tax_id="",
    settings={},
    timezone="Asia/Kolkata",
)


def _patient(**kwargs):
    base = {"id": uuid4(), "first_name": "Priya", "last_name": "Raman"}
    return SimpleNamespace(**{**base, **kwargs})


def test_age_counts_whole_years_up_to_the_issue_date() -> None:
    patient = _patient(date_of_birth=date(1992, 3, 14))
    assert DocumentPDFService._patient_age(patient, date(2026, 3, 13), EN) == "33 years"
    assert DocumentPDFService._patient_age(patient, date(2026, 3, 14), EN) == "34 years"
    assert DocumentPDFService._patient_age(_patient(date_of_birth=None), date(2026, 1, 1), EN) == "-"


def test_gender_is_localized_and_private_values_stay_blank() -> None:
    assert DocumentPDFService._patient_gender(_patient(gender="female"), EN) == "Female"
    assert DocumentPDFService._patient_gender(_patient(gender="prefer_not_say"), EN) == "-"
    assert DocumentPDFService._patient_gender(_patient(gender=None), EN) == "-"


def test_document_shows_age_gender_doctor_and_indian_address_order() -> None:
    doc = SimpleNamespace(document_type="medical_certificate", content={"diagnosis": "Caries"})
    patient = _patient(date_of_birth=date(1990, 1, 1), gender="female")
    html = DocumentPDFService._generate_html(doc, CLINIC, patient, "en", "Dr. Arun Kumar")
    for text in ("Age", "years", "Gender", "Female", "Doctor", "Dr. Arun Kumar", "Chennai 600001"):
        assert text in html, text
    assert "@page" in html


def test_create_keeps_the_chosen_doctor() -> None:
    doctor = uuid4()
    data = DocumentCreate(
        patient_id=uuid4(),
        document_type="prescription",
        title="Rx",
        content={"doctor_id": str(doctor), "diagnosis": "Pulpitis", "medications": []},
    )
    assert data.content["doctor_id"] == str(doctor)
