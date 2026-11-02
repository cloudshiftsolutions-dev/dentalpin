"""Pydantic schemas for the recalls module."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

# --- Enum literals (mirrors ``models.REASONS`` etc.) ----------------------

Reason = Literal[
    "hygiene",
    "checkup",
    "ortho_review",
    "implant_review",
    "post_op",
    "treatment_followup",
    "other",
]

Priority = Literal["low", "normal", "high"]

Status = Literal[
    "pending",
    "contacted_no_answer",
    "contacted_scheduled",
    "contacted_declined",
    "done",
    "cancelled",
    "needs_review",
]

Channel = Literal["phone", "whatsapp", "sms", "email"]

Outcome = Literal[
    "no_answer",
    "voicemail",
    "scheduled",
    "declined",
    "wrong_number",
]

IntervalUnit = Literal["day", "week", "month"]

# Longest default interval per unit. 60 months is the cap the settings
# form always had; days and weeks stop at about two years.
INTERVAL_MAX: dict[str, int] = {"day": 730, "week": 104, "month": 60}


# --- Recall CRUD -----------------------------------------------------------


class RecallCreate(BaseModel):
    patient_id: UUID
    due_month: date  # caller passes day-1 of target month; service normalises
    due_date: date | None = None
    reason: Reason
    reason_note: str | None = None
    priority: Priority = "normal"
    assigned_professional_id: UUID | None = None
    linked_treatment_id: UUID | None = None
    linked_treatment_category_key: str | None = Field(default=None, max_length=80)


class RecallUpdate(BaseModel):
    due_month: date | None = None
    due_date: date | None = None
    reason: Reason | None = None
    reason_note: str | None = None
    priority: Priority | None = None
    assigned_professional_id: UUID | None = None


class RecallSnoozeRequest(BaseModel):
    months: int = Field(ge=1, le=24)
    reason_note: str | None = None


class RecallCancelRequest(BaseModel):
    note: str | None = None


class RecallLinkAppointmentRequest(BaseModel):
    appointment_id: UUID


class AttemptCreate(BaseModel):
    channel: Channel
    outcome: Outcome
    note: str | None = None
    # When the receptionist books an appointment in the same gesture as
    # logging the attempt, this lets the call-list UI close the loop in
    # one server round-trip.
    linked_appointment_id: UUID | None = None


# --- Response shapes -------------------------------------------------------


class PatientBriefForRecall(BaseModel):
    id: UUID
    first_name: str
    last_name: str
    phone: str | None = None
    email: str | None = None
    do_not_contact: bool = False
    status: str

    model_config = ConfigDict(from_attributes=True)


class AttemptResponse(BaseModel):
    id: UUID
    recall_id: UUID
    attempted_at: datetime
    attempted_by: UUID
    channel: Channel
    outcome: Outcome
    note: str | None = None

    model_config = ConfigDict(from_attributes=True)


class RecallResponse(BaseModel):
    id: UUID
    clinic_id: UUID
    patient_id: UUID
    due_month: date
    due_date: date | None = None
    reason: Reason
    reason_note: str | None = None
    priority: Priority
    status: Status
    recommended_by: UUID | None = None
    assigned_professional_id: UUID | None = None
    last_contact_attempt_at: datetime | None = None
    contact_attempt_count: int
    linked_appointment_id: UUID | None = None
    linked_treatment_id: UUID | None = None
    linked_treatment_category_key: str | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    patient: PatientBriefForRecall | None = None

    model_config = ConfigDict(from_attributes=True)


class RecallDetailResponse(RecallResponse):
    attempts: list[AttemptResponse] = []


# --- Suggestions -----------------------------------------------------------


class RecallSuggestion(BaseModel):
    """A non-binding suggestion the UI surfaces in the patient feed.

    The ``recalls`` module never auto-creates from suggestions — the
    user clicks "create" to commit. Returned by
    ``GET /api/v1/recalls/suggestions/next``.
    """

    patient_id: UUID
    reason: Reason
    due_month: date
    # Exact day, set when the interval is in days or weeks.
    due_date: date | None = None
    interval_value: int
    interval_unit: IntervalUnit = "month"
    # Kept for older clients: the interval when it is in months, else 0.
    interval_months: int
    treatment_category_key: str | None = None
    treatment_id: UUID | None = None
    matched_setting: bool


# --- Settings --------------------------------------------------------------


class RecallSettingsResponse(BaseModel):
    clinic_id: UUID
    reason_intervals: dict[str, int]
    # Unit of each ``reason_intervals`` entry; a missing reason is months.
    reason_interval_units: dict[str, IntervalUnit] = Field(default_factory=dict)
    category_to_reason: dict[str, str]
    auto_suggest_on_treatment_completed: bool
    auto_link_on_appointment_scheduled: bool
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RecallSettingsUpdate(BaseModel):
    reason_intervals: dict[Reason, int] | None = None
    reason_interval_units: dict[Reason, IntervalUnit] | None = None
    category_to_reason: dict[str, str] | None = None
    auto_suggest_on_treatment_completed: bool | None = None
    auto_link_on_appointment_scheduled: bool | None = None

    @model_validator(mode="after")
    def _intervals_in_range(self) -> RecallSettingsUpdate:
        units = self.reason_interval_units or {}
        for reason, value in (self.reason_intervals or {}).items():
            # Without a unit in this request the stored one applies, which
            # may be days — so only the widest bound can be checked here.
            unit = units.get(reason)
            limit = INTERVAL_MAX[unit] if unit else max(INTERVAL_MAX.values())
            if not 0 <= value <= limit:
                label = f"{unit}s" if unit else "days"
                raise ValueError(f"Interval for '{reason}' must be between 0 and {limit} {label}.")
        return self


# --- Stats -----------------------------------------------------------------


class RecallDashboardStats(BaseModel):
    due_this_week: int
    due_this_month: int
    overdue: int
    scheduled_this_month: int
    completed_this_month: int
    conversion_rate: float  # 0.0 - 1.0
