"""Event handlers for the patient_timeline module.

Every handler follows the same contract:

- Signature ``async def on_*(data: dict) -> None`` — matches the event bus
  calling convention (``handler(data)``).
- Opens its own DB session via :func:`async_session_maker`, commits on
  success and rolls back on failure — deliberately own-session (ADR 0019,
  audited in issue #183): the timeline is a log and must never be able to
  fail the event it is logging.
- Never imports models from other modules. Everything it needs must come in
  the ``data`` dict. Keeps the timeline module removable in isolation — the
  whole point of the patient_timeline split in Fase B.3.
- Skips events without a ``patient_id`` (administrative/clinic-scoped events
  have nowhere to land in the ficha del paciente).
- Titles are stored as rendered text, so they are rendered in the clinic's
  ``communication_language`` (falling back to ``settings.CONTENT_LOCALE``)
  at write time. Handlers pass :func:`_t` message keys, never literals.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.events import EventType
from app.database import async_session_maker

from .service import TimelineService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Localized copy
# ---------------------------------------------------------------------------

_MESSAGES: dict[str, dict[str, str]] = {
    # Visits
    "consultation": {"es": "Consulta", "en": "Consultation"},
    "appointment_scheduled": {
        "es": "Cita programada: {treatment}",
        "en": "Appointment scheduled: {treatment}",
    },
    "appointment_completed": {
        "es": "Cita completada: {treatment}",
        "en": "Appointment completed: {treatment}",
    },
    "appointment_cancelled": {
        "es": "Cita cancelada: {treatment}",
        "en": "Appointment cancelled: {treatment}",
    },
    "appointment_no_show": {
        "es": "Paciente no asistió: {treatment}",
        "en": "Patient did not attend: {treatment}",
    },
    "appointment_confirmed": {
        "es": "Cita confirmada: {treatment}",
        "en": "Appointment confirmed: {treatment}",
    },
    "appointment_checked_in": {
        "es": "Paciente llegó a la clínica ({treatment})",
        "en": "Patient arrived at the clinic ({treatment})",
    },
    "appointment_in_treatment": {
        "es": "Paciente en gabinete ({treatment})",
        "en": "Patient in the treatment room ({treatment})",
    },
    # Treatments
    "treatment_generic": {"es": "tratamiento", "en": "treatment"},
    "treatment_performed": {
        "es": "Tratamiento realizado: {name}",
        "en": "Treatment performed: {name}",
    },
    "teeth": {"es": "Dientes: {teeth}", "en": "Teeth: {teeth}"},
    "plan_created": {
        "es": "Plan de tratamiento creado: {name}",
        "en": "Treatment plan created: {name}",
    },
    "plan_created_bare": {"es": "Plan de tratamiento creado", "en": "Treatment plan created"},
    "plan_item_completed": {
        "es": "Tratamiento del plan completado: {name}",
        "en": "Plan treatment completed: {name}",
    },
    "plan_item_completed_bare": {
        "es": "Tratamiento del plan completado",
        "en": "Plan treatment completed",
    },
    "plan_confirmed": {"es": "Plan confirmado: {number}", "en": "Plan confirmed: {number}"},
    "plan_confirmed_bare": {"es": "Plan confirmado", "en": "Plan confirmed"},
    "plan_closed": {"es": "Plan cerrado ({reason})", "en": "Plan closed ({reason})"},
    "plan_reactivated": {"es": "Plan reactivado", "en": "Plan reactivated"},
    # Financial
    "budget_sent": {"es": "Presupuesto enviado: {number}", "en": "Budget sent: {number}"},
    "budget_sent_bare": {"es": "Presupuesto enviado", "en": "Budget sent"},
    "budget_accepted": {
        "es": "Presupuesto aceptado: {number}",
        "en": "Budget accepted: {number}",
    },
    "budget_accepted_bare": {"es": "Presupuesto aceptado", "en": "Budget accepted"},
    "budget_rejected": {
        "es": "Presupuesto rechazado: {number}",
        "en": "Budget rejected: {number}",
    },
    "budget_rejected_bare": {"es": "Presupuesto rechazado", "en": "Budget rejected"},
    "budget_expired": {"es": "Presupuesto caducado: {number}", "en": "Budget expired: {number}"},
    "budget_expired_bare": {"es": "Presupuesto caducado", "en": "Budget expired"},
    "budget_renegotiated": {
        "es": "Presupuesto en renegociación",
        "en": "Budget under renegotiation",
    },
    "budget_viewed": {
        "es": "Presupuesto visto por el paciente",
        "en": "Budget viewed by the patient",
    },
    "budget_reminder": {
        "es": "Recordatorio enviado ({days}d)",
        "en": "Reminder sent ({days}d)",
    },
    "budget_reminder_bare": {"es": "Recordatorio enviado", "en": "Reminder sent"},
    "invoice_issued": {"es": "Factura emitida: {number}", "en": "Invoice issued: {number}"},
    "invoice_issued_bare": {"es": "Factura emitida", "en": "Invoice issued"},
    "invoice_paid": {"es": "Factura pagada: {number}", "en": "Invoice paid: {number}"},
    "invoice_paid_bare": {"es": "Factura pagada", "en": "Invoice paid"},
    # Communications
    "channel_generic": {"es": "Mensaje", "en": "Message"},
    "message_generic": {"es": "mensaje", "en": "message"},
    "notification_sent": {"es": "{channel} enviado: {subject}", "en": "{channel} sent: {subject}"},
    "notification_reply": {
        "es": "Respuesta recibida por WhatsApp",
        "en": "WhatsApp reply received",
    },
    "notification_failed": {
        "es": "{channel} fallido: {subject}",
        "en": "{channel} failed: {subject}",
    },
    # Medical history
    "medical_context": {"es": "Contexto médico actualizado", "en": "Medical context updated"},
    "medical_history": {"es": "Historial médico actualizado", "en": "Medical history updated"},
    "medical_generic": {"es": "Historia clínica actualizada", "en": "Medical record updated"},
    # Documents
    "document_generic": {"es": "Documento", "en": "Document"},
    "document": {"es": "Documento: {title}", "en": "Document: {title}"},
    "photo_generic": {"es": "Foto", "en": "Photo"},
    "xray": {"es": "Radiografía", "en": "X-ray"},
    "clinical_photo": {"es": "Foto clínica", "en": "Clinical photo"},
    "photo_title": {"es": "{kind}: {title}", "en": "{kind}: {title}"},
    "photo_chip": {"es": "{kind} · {suffix}", "en": "{kind} · {suffix}"},
    "pair_created": {
        "es": "Comparativa antes/después creada",
        "en": "Before/after comparison created",
    },
    # Clinical notes
    "note_administrative": {"es": "Nota administrativa", "en": "Administrative note"},
    "note_diagnosis": {"es": "Nota de diagnóstico", "en": "Diagnosis note"},
    "note_treatment": {"es": "Nota clínica en tratamiento", "en": "Treatment clinical note"},
    "note_treatment_plan": {
        "es": "Nota clínica en plan de tratamiento",
        "en": "Treatment plan clinical note",
    },
    "note_generic": {"es": "Nota clínica", "en": "Clinical note"},
    "note_with_tooth": {"es": "{title} (diente {tooth})", "en": "{title} (tooth {tooth})"},
    "visit_note": {"es": "Nota clínica de visita", "en": "Visit clinical note"},
    "treatment_capitalized": {"es": "Tratamiento", "en": "Treatment"},
    "completed_without_note": {
        "es": "{name} completado sin nota",
        "en": "{name} completed without a note",
    },
    # Prescriptions / imaging / orthodontics
    "prescription_issued": {"es": "Receta emitida", "en": "Prescription issued"},
    "prescription_cancelled": {"es": "Receta cancelada", "en": "Prescription cancelled"},
    "imaging_study": {"es": "Estudio de imagen", "en": "Imaging study"},
    "ortho_case_created": {"es": "Caso de ortodoncia abierto", "en": "Orthodontic case opened"},
    "ortho_case_status": {
        "es": "Estado de ortodoncia actualizado",
        "en": "Orthodontic status updated",
    },
    "ortho_control": {"es": "Control de ortodoncia", "en": "Orthodontic check-up"},
}


@dataclass(frozen=True)
class _Text:
    key: str
    params: dict[str, Any] = field(default_factory=dict)


def _t(key: str, **params: Any) -> _Text:
    return _Text(key, params)


def _render(value: Any, locale: str) -> Any:
    """Render a :class:`_Text` (params may nest) in ``locale``; pass anything else through."""
    if not isinstance(value, _Text):
        return value
    table = _MESSAGES[value.key]
    template = table.get(locale) or table.get(settings.CONTENT_LOCALE) or table["es"]
    return template.format(**{k: _render(v, locale) for k, v in value.params.items()})


async def _clinic_locale(db: AsyncSession, clinic_id: UUID) -> str:
    # Same lookup as notifications.resolve_clinic_communication_locale,
    # inlined so the timeline stays removable without that module.
    row = (
        await db.execute(text("SELECT settings FROM clinics WHERE id = :id"), {"id": clinic_id})
    ).first()
    clinic_settings = row.settings if row else None
    lang = (
        clinic_settings.get("communication_language") if isinstance(clinic_settings, dict) else None
    )
    return lang or settings.CONTENT_LOCALE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_dt(value: Any) -> datetime:
    """Parse an ISO timestamp; fall back to now if missing/invalid."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.now(UTC)


def _required_ids(data: dict, *keys: str) -> tuple[UUID, ...] | None:
    """Return tuple of UUIDs for the given keys, or None if any are missing/invalid."""
    try:
        return tuple(UUID(data[k]) for k in keys)
    except (KeyError, TypeError, ValueError):
        return None


async def _record(
    event_type: str,
    event_category: str,
    source_table: str,
    data: dict,
    *,
    source_id_key: str,
    title: str | _Text,
    description: str | _Text | None = None,
    event_data: dict | None = None,
    occurred_at_key: str = "occurred_at",
    created_by_key: str | None = None,
) -> None:
    """Generic helper: insert one timeline row and commit.

    Centralizes session management + error handling so each specific handler
    stays declarative.

    own-session (issue #183): every handler in this module is payload-only —
    the timeline records what the payload says happened and never re-reads
    the publisher's rows, and ``source_id`` is polymorphic with no FK. The
    timeline is a log: it must not be able to fail the thing it is logging.
    """
    ids = _required_ids(data, "clinic_id", "patient_id", source_id_key)
    if ids is None:
        # Not enough info to attach to a patient — silently skip. These events
        # are valid at the clinic level (e.g. admin emails without a patient)
        # and simply don't belong on any single ficha.
        return
    clinic_id, patient_id, source_id = ids

    created_by: UUID | None = None
    if created_by_key and data.get(created_by_key):
        try:
            created_by = UUID(data[created_by_key])
        except (TypeError, ValueError):
            created_by = None

    async with async_session_maker() as db:
        try:
            locale = await _clinic_locale(db, clinic_id)
            await TimelineService.add_entry(
                db=db,
                clinic_id=clinic_id,
                patient_id=patient_id,
                event_type=event_type,
                event_category=event_category,
                source_table=source_table,
                source_id=source_id,
                title=_render(title, locale),
                description=_render(description, locale),
                event_data=(
                    {k: _render(v, locale) for k, v in event_data.items()}
                    if event_data
                    else event_data
                ),
                occurred_at=_parse_dt(data.get(occurred_at_key)),
                created_by=created_by,
            )
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("patient_timeline: failed to record %s", event_type)


# ---------------------------------------------------------------------------
# Visits
# ---------------------------------------------------------------------------


def _treatment(data: dict) -> str | _Text:
    return data.get("treatment_type") or _t("consultation")


async def on_appointment_scheduled(data: dict) -> None:
    await _record(
        event_type=EventType.APPOINTMENT_SCHEDULED,
        event_category="visit",
        source_table="appointments",
        data=data,
        source_id_key="appointment_id",
        title=_t("appointment_scheduled", treatment=_treatment(data)),
        event_data={
            "cabinet": data.get("cabinet"),
            "professional_id": data.get("professional_id"),
            "start_time": data.get("start_time"),
        },
        occurred_at_key="start_time",
    )


async def on_appointment_completed(data: dict) -> None:
    await _record(
        event_type=EventType.APPOINTMENT_COMPLETED,
        event_category="visit",
        source_table="appointments",
        data=data,
        source_id_key="appointment_id",
        title=_t("appointment_completed", treatment=_treatment(data)),
        description=data.get("notes"),
        event_data={
            "cabinet": data.get("cabinet"),
            "professional_id": data.get("professional_id"),
        },
        occurred_at_key="end_time",
    )


async def on_appointment_cancelled(data: dict) -> None:
    await _record(
        event_type=EventType.APPOINTMENT_CANCELLED,
        event_category="visit",
        source_table="appointments",
        data=data,
        source_id_key="appointment_id",
        title=_t("appointment_cancelled", treatment=_treatment(data)),
        event_data={"professional_id": data.get("professional_id")},
    )


async def on_appointment_no_show(data: dict) -> None:
    await _record(
        event_type=EventType.APPOINTMENT_NO_SHOW,
        event_category="visit",
        source_table="appointments",
        data=data,
        source_id_key="appointment_id",
        title=_t("appointment_no_show", treatment=_treatment(data)),
        event_data={
            "cabinet": data.get("cabinet"),
            "professional_id": data.get("professional_id"),
        },
        occurred_at_key="start_time",
    )


async def on_appointment_confirmed(data: dict) -> None:
    await _record(
        event_type=EventType.APPOINTMENT_CONFIRMED,
        event_category="visit",
        source_table="appointments",
        data=data,
        source_id_key="appointment_id",
        title=_t("appointment_confirmed", treatment=_treatment(data)),
        event_data={"professional_id": data.get("professional_id")},
        occurred_at_key="changed_at",
        created_by_key="changed_by",
    )


async def on_appointment_checked_in(data: dict) -> None:
    await _record(
        event_type=EventType.APPOINTMENT_CHECKED_IN,
        event_category="visit",
        source_table="appointments",
        data=data,
        source_id_key="appointment_id",
        title=_t("appointment_checked_in", treatment=_treatment(data)),
        event_data={
            "cabinet": data.get("cabinet"),
            "professional_id": data.get("professional_id"),
        },
        occurred_at_key="changed_at",
        created_by_key="changed_by",
    )


async def on_appointment_in_treatment(data: dict) -> None:
    await _record(
        event_type=EventType.APPOINTMENT_IN_TREATMENT,
        event_category="visit",
        source_table="appointments",
        data=data,
        source_id_key="appointment_id",
        title=_t("appointment_in_treatment", treatment=_treatment(data)),
        event_data={
            "cabinet": data.get("cabinet"),
            "professional_id": data.get("professional_id"),
        },
        occurred_at_key="changed_at",
        created_by_key="changed_by",
    )


# ---------------------------------------------------------------------------
# Treatments
# ---------------------------------------------------------------------------


async def on_tooth_treatment_performed(data: dict) -> None:
    name = data.get("treatment_name") or data.get("clinical_type") or _t("treatment_generic")
    teeth = data.get("tooth_numbers") or []
    teeth_label = ", ".join(str(t) for t in teeth) if teeth else None
    await _record(
        event_type=EventType.ODONTOGRAM_TREATMENT_PERFORMED,
        event_category="treatment",
        source_table="treatments",
        data=data,
        source_id_key="treatment_id",
        title=_t("treatment_performed", name=name),
        description=_t("teeth", teeth=teeth_label) if teeth_label else None,
        event_data={
            "clinical_type": data.get("clinical_type"),
            "tooth_numbers": teeth,
        },
        occurred_at_key="performed_at",
        created_by_key="performed_by",
    )


async def on_plan_created(data: dict) -> None:
    plan_name = data.get("plan_name") or f"Plan {data.get('plan_number', '')}".strip()
    await _record(
        event_type=EventType.TREATMENT_PLAN_CREATED,
        event_category="treatment",
        source_table="treatment_plans",
        data=data,
        source_id_key="plan_id",
        title=_t("plan_created", name=plan_name) if plan_name else _t("plan_created_bare"),
        event_data={"plan_number": data.get("plan_number")},
        created_by_key="created_by",
    )


async def on_plan_item_completed(data: dict) -> None:
    item_name = data.get("item_name")
    title = (
        _t("plan_item_completed", name=item_name) if item_name else _t("plan_item_completed_bare")
    )
    await _record(
        event_type=EventType.TREATMENT_PLAN_TREATMENT_COMPLETED,
        event_category="treatment",
        source_table="planned_treatment_items",
        data=data,
        source_id_key="item_id",
        title=title,
        event_data={"plan_id": data.get("plan_id")},
        created_by_key="completed_by",
    )


# ---------------------------------------------------------------------------
# Financial
# ---------------------------------------------------------------------------


async def on_budget_sent(data: dict) -> None:
    number = data.get("budget_number")
    await _record(
        event_type=EventType.BUDGET_SENT,
        event_category="financial",
        source_table="budgets",
        data=data,
        source_id_key="budget_id",
        title=_t("budget_sent", number=number) if number else _t("budget_sent_bare"),
        event_data={
            "budget_number": number,
            "total": data.get("total"),
            "send_method": data.get("send_method"),
        },
    )


async def on_budget_accepted(data: dict) -> None:
    number = data.get("budget_number")
    await _record(
        event_type=EventType.BUDGET_ACCEPTED,
        event_category="financial",
        source_table="budgets",
        data=data,
        source_id_key="budget_id",
        title=_t("budget_accepted", number=number) if number else _t("budget_accepted_bare"),
        event_data={
            "budget_number": number,
            "total": data.get("total"),
            "accepted_via": data.get("accepted_via"),
        },
    )


async def on_budget_rejected(data: dict) -> None:
    number = data.get("budget_number")
    await _record(
        event_type=EventType.BUDGET_REJECTED,
        event_category="financial",
        source_table="budgets",
        data=data,
        source_id_key="budget_id",
        title=_t("budget_rejected", number=number) if number else _t("budget_rejected_bare"),
        event_data={
            "budget_number": number,
            "rejection_reason": data.get("rejection_reason"),
            "rejection_note": data.get("rejection_note"),
        },
    )


async def on_budget_expired(data: dict) -> None:
    number = data.get("budget_number")
    await _record(
        event_type=EventType.BUDGET_EXPIRED,
        event_category="financial",
        source_table="budgets",
        data=data,
        source_id_key="budget_id",
        title=_t("budget_expired", number=number) if number else _t("budget_expired_bare"),
        event_data={
            "budget_number": number,
            "days_overdue": data.get("days_overdue"),
        },
    )


async def on_budget_renegotiated(data: dict) -> None:
    await _record(
        event_type=EventType.BUDGET_RENEGOTIATED,
        event_category="financial",
        source_table="budgets",
        data=data,
        source_id_key="budget_id",
        title=_t("budget_renegotiated"),
        event_data={"plan_id": data.get("plan_id")},
    )


async def on_budget_viewed(data: dict) -> None:
    await _record(
        event_type=EventType.BUDGET_VIEWED,
        event_category="financial",
        source_table="budgets",
        data=data,
        source_id_key="budget_id",
        title=_t("budget_viewed"),
        occurred_at_key="viewed_at",
    )


async def on_budget_reminder_sent(data: dict) -> None:
    milestone = data.get("milestone_days")
    await _record(
        event_type=EventType.BUDGET_REMINDER_SENT,
        event_category="financial",
        source_table="budgets",
        data=data,
        source_id_key="budget_id",
        title=_t("budget_reminder", days=milestone) if milestone else _t("budget_reminder_bare"),
        occurred_at_key="sent_at",
        event_data={"milestone_days": milestone},
    )


async def on_treatment_plan_confirmed(data: dict) -> None:
    plan_number = data.get("plan_number")
    await _record(
        event_type=EventType.TREATMENT_PLAN_CONFIRMED,
        event_category="treatment",
        source_table="treatment_plans",
        data=data,
        source_id_key="plan_id",
        title=(
            _t("plan_confirmed", number=plan_number) if plan_number else _t("plan_confirmed_bare")
        ),
        occurred_at_key="confirmed_at",
        created_by_key="confirmed_by_user_id",
        event_data={
            "plan_number": plan_number,
            "total_estimated": data.get("total_estimated"),
        },
    )


async def on_treatment_plan_closed(data: dict) -> None:
    reason = data.get("closure_reason") or "other"
    await _record(
        event_type=EventType.TREATMENT_PLAN_CLOSED,
        event_category="treatment",
        source_table="treatment_plans",
        data=data,
        source_id_key="plan_id",
        title=_t("plan_closed", reason=reason),
        occurred_at_key="closed_at",
        created_by_key="closed_by_user_id",
        event_data={
            "closure_reason": reason,
            "closure_note": data.get("closure_note"),
            "previous_status": data.get("previous_status"),
        },
    )


async def on_treatment_plan_reactivated(data: dict) -> None:
    await _record(
        event_type=EventType.TREATMENT_PLAN_REACTIVATED,
        event_category="treatment",
        source_table="treatment_plans",
        data=data,
        source_id_key="plan_id",
        title=_t("plan_reactivated"),
        occurred_at_key="reactivated_at",
        created_by_key="reactivated_by_user_id",
        event_data={
            "previous_closure_reason": data.get("previous_closure_reason"),
        },
    )


async def on_invoice_issued(data: dict) -> None:
    number = data.get("invoice_number")
    await _record(
        event_type=EventType.INVOICE_ISSUED,
        event_category="financial",
        source_table="invoices",
        data=data,
        source_id_key="invoice_id",
        title=_t("invoice_issued", number=number) if number else _t("invoice_issued_bare"),
        event_data={"invoice_number": number, "total": data.get("total")},
    )


async def on_invoice_paid(data: dict) -> None:
    number = data.get("invoice_number")
    await _record(
        event_type=EventType.INVOICE_PAID,
        event_category="financial",
        source_table="invoices",
        data=data,
        source_id_key="invoice_id",
        title=_t("invoice_paid", number=number) if number else _t("invoice_paid_bare"),
        event_data={"invoice_number": number, "total": data.get("total")},
    )


# ---------------------------------------------------------------------------
# Communications
# ---------------------------------------------------------------------------


# Human labels for the outbound channels the gateway publishes. Anything
# unknown falls back to a generic "Message" so a future channel still lands
# on the timeline without a code change here.
_CHANNEL_LABELS = {"email": "Email", "whatsapp": "WhatsApp"}


def _channel_label(data: dict) -> str | _Text:
    channel = data.get("channel") or ""
    return _CHANNEL_LABELS.get(channel) or _t("channel_generic")


def _subject(data: dict) -> str | _Text:
    return data.get("subject") or data.get("template_key") or _t("message_generic")


async def on_notification_sent(data: dict) -> None:
    """Record any outbound send (every channel) from ``notification.sent``.

    Replaces the legacy ``email.sent`` subscription: the gateway publishes
    the generic event for email AND WhatsApp, so subscribing to both would
    double-record email sends (issue #287 bug 12).
    """
    await _record(
        event_type=EventType.NOTIFICATION_SENT,
        event_category="communication",
        source_table="communication_messages",
        data=data,
        source_id_key="message_id",
        title=_t("notification_sent", channel=_channel_label(data), subject=_subject(data)),
        event_data={
            "channel": data.get("channel"),
            "template_key": data.get("template_key"),
        },
    )


async def on_notification_reply_received(data: dict) -> None:
    await _record(
        event_type=EventType.NOTIFICATION_REPLY_RECEIVED,
        event_category="communication",
        source_table="communication_messages",
        data=data,
        source_id_key="message_id",
        title=_t("notification_reply"),
        description=data.get("reply_text"),
        event_data={
            "channel": data.get("channel"),
            "from_address": data.get("from_address"),
        },
    )


async def on_notification_failed(data: dict) -> None:
    """Record a failed outbound send (every channel) from ``notification.failed``."""
    await _record(
        event_type=EventType.NOTIFICATION_FAILED,
        event_category="communication",
        source_table="communication_messages",
        data=data,
        source_id_key="message_id",
        title=_t("notification_failed", channel=_channel_label(data), subject=_subject(data)),
        description=data.get("error_message"),
        event_data={
            "channel": data.get("channel"),
            "template_key": data.get("template_key"),
            "error_message": data.get("error_message"),
        },
    )


# ---------------------------------------------------------------------------
# Medical history
# ---------------------------------------------------------------------------


_MEDICAL_SECTION_TITLES = {"context": "medical_context", "history": "medical_history"}


async def on_medical_updated(data: dict) -> None:
    # patient_timeline uses patient_id as the source_id for medical updates —
    # there is no per-update row to point to. Inject it so the generic helper
    # passes the required-ids check.
    data = {**data, "source_id": data.get("patient_id")}
    section = data.get("section")
    # The event_category badge already shows "Historial médico" and the
    # description carries the human summary — keep the title short and
    # avoid leaking internal section slugs like "history" / "context".
    # Known sections get localized copy; the publisher's summary is Spanish.
    section_key = _MEDICAL_SECTION_TITLES.get(section or "")
    title = _t(section_key) if section_key else (data.get("summary") or _t("medical_generic"))
    await _record(
        event_type=EventType.PATIENT_MEDICAL_UPDATED,
        event_category="medical",
        source_table="patients",
        data=data,
        source_id_key="source_id",
        title=title,
        event_data={"section": section},
        created_by_key="user_id",
    )


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


async def on_document_uploaded(data: dict) -> None:
    title = data.get("title") or _t("document_generic")
    media_kind = data.get("media_kind") or "document"
    # Photos / X-rays get their own dedicated card via on_photo_uploaded.
    # Skip the generic document row to avoid duplicate timeline entries.
    if media_kind in ("photo", "xray"):
        return
    await _record(
        event_type=EventType.DOCUMENT_UPLOADED,
        event_category="document",
        source_table="documents",
        data=data,
        source_id_key="document_id",
        title=_t("document", title=title),
        event_data={"document_type": data.get("document_type")},
    )


async def on_photo_uploaded(data: dict) -> None:
    """Photo / X-ray-aware variant — surfaces thumbnail-friendly metadata."""
    title = data.get("title") or _t("photo_generic")
    media_kind = data.get("media_kind") or "photo"
    category = data.get("media_category")
    subtype = data.get("media_subtype")
    label_kind = _t("xray") if media_kind == "xray" else _t("clinical_photo")
    chip_suffix = subtype or category
    await _record(
        event_type=EventType.PHOTO_UPLOADED,
        event_category="document",
        source_table="documents",
        data=data,
        source_id_key="document_id",
        title=_t("photo_title", kind=label_kind, title=title),
        event_data={
            "media_kind": media_kind,
            "media_category": category,
            "media_subtype": subtype,
            "captured_at": data.get("captured_at"),
            "chip": (
                _t("photo_chip", kind=label_kind, suffix=chip_suffix) if chip_suffix else label_kind
            ),
        },
        occurred_at_key="captured_at",
    )


async def on_pair_created(data: dict) -> None:
    await _record(
        event_type=EventType.PAIR_CREATED,
        event_category="document",
        source_table="documents",
        data=data,
        source_id_key="document_a_id",
        title=_t("pair_created"),
        event_data={
            "document_a_id": data.get("document_a_id"),
            "document_b_id": data.get("document_b_id"),
        },
    )


# ---------------------------------------------------------------------------
# Clinical notes
# ---------------------------------------------------------------------------


_NOTE_TYPE_TITLES = {
    "administrative": "note_administrative",
    "diagnosis": "note_diagnosis",
    "treatment": "note_treatment",
    "treatment_plan": "note_treatment_plan",
}


async def on_clinical_note_created(data: dict) -> None:
    """Record any clinical_notes-module note on the patient timeline.

    A single handler covers all four note_types (administrative, diagnosis,
    treatment, treatment_plan). The event_type field stays specific so the
    timeline UI can filter by note category.
    """
    event_type_str = f"clinical_notes.{data.get('note_type', 'note')}_created"
    note_type = data.get("note_type") or "note"
    title = _t(_NOTE_TYPE_TITLES.get(note_type, "note_generic"))
    tooth = data.get("tooth_number")
    if note_type == "diagnosis" and tooth:
        title = _t("note_with_tooth", title=title, tooth=tooth)

    data = {**data, "source_id": data.get("note_id")}
    excerpt = data.get("body_excerpt") or ""
    await _record(
        event_type=event_type_str,
        event_category="note",
        source_table="clinical_notes",
        data=data,
        source_id_key="source_id",
        title=title,
        description=excerpt or None,
        event_data={
            "note_type": note_type,
            "owner_type": data.get("owner_type"),
            "owner_id": data.get("owner_id"),
            "tooth_number": tooth,
        },
        created_by_key="user_id",
    )


async def on_visit_note_updated(data: dict) -> None:
    """Record a visit-level clinical note (AppointmentTreatment.notes)."""
    data = {**data, "source_id": data.get("appointment_treatment_id")}
    excerpt = data.get("body_excerpt") or ""
    await _record(
        event_type=EventType.AGENDA_VISIT_NOTE_UPDATED,
        event_category="note",
        source_table="appointment_treatments",
        data=data,
        source_id_key="source_id",
        title=_t("visit_note"),
        description=excerpt or None,
        event_data={
            "appointment_id": data.get("appointment_id"),
            "plan_item_id": data.get("plan_item_id"),
        },
        created_by_key="user_id",
    )


async def on_item_completed_without_note(data: dict) -> None:
    """Audit a plan-item completion where the clinician skipped the note."""
    data = {**data, "source_id": data.get("plan_item_id")}
    item_name = data.get("item_name") or _t("treatment_capitalized")
    await _record(
        event_type=EventType.TREATMENT_PLAN_ITEM_COMPLETED_WITHOUT_NOTE,
        event_category="treatment",
        source_table="planned_treatment_items",
        data=data,
        source_id_key="source_id",
        title=_t("completed_without_note", name=item_name),
        event_data={"plan_id": data.get("plan_id")},
        created_by_key="user_id",
    )


# ---------------------------------------------------------------------------
# Prescriptions
# ---------------------------------------------------------------------------


async def on_prescription_issued(data: dict) -> None:
    data = {**data, "source_id": data.get("prescription_id")}
    await _record(
        event_type=EventType.PRESCRIPTION_ISSUED,
        event_category="treatment",
        source_table="prescriptions",
        data=data,
        source_id_key="source_id",
        title=_t("prescription_issued"),
    )


async def on_prescription_cancelled(data: dict) -> None:
    data = {**data, "source_id": data.get("prescription_id")}
    await _record(
        event_type=EventType.PRESCRIPTION_CANCELLED,
        event_category="treatment",
        source_table="prescriptions",
        data=data,
        source_id_key="source_id",
        title=_t("prescription_cancelled"),
    )


async def on_imaging_study_indexed(data: dict) -> None:
    data = {**data, "source_id": data.get("study_id")}
    await _record(
        event_type=EventType.IMAGING_STUDY_INDEXED,
        event_category="treatment",
        source_table="imaging_studies",
        data=data,
        source_id_key="source_id",
        title=_t("imaging_study"),
    )


# ---------------------------------------------------------------------------
# Orthodontics
# ---------------------------------------------------------------------------


async def on_ortho_case_created(data: dict) -> None:
    data = {**data, "source_id": data.get("case_id")}
    await _record(
        event_type=EventType.ORTHODONTICS_CASE_CREATED,
        event_category="treatment",
        source_table="ortho_cases",
        data=data,
        source_id_key="source_id",
        title=_t("ortho_case_created"),
    )


async def on_ortho_case_status_changed(data: dict) -> None:
    data = {**data, "source_id": data.get("case_id")}
    await _record(
        event_type=EventType.ORTHODONTICS_CASE_STATUS_CHANGED,
        event_category="treatment",
        source_table="ortho_cases",
        data=data,
        source_id_key="source_id",
        title=_t("ortho_case_status"),
    )


async def on_ortho_control_registered(data: dict) -> None:
    data = {**data, "source_id": data.get("control_id")}
    await _record(
        event_type=EventType.ORTHODONTICS_CONTROL_REGISTERED,
        event_category="treatment",
        source_table="ortho_controls",
        data=data,
        source_id_key="source_id",
        title=_t("ortho_control"),
    )
