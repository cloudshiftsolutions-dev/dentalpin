"""Event handlers for the orthodontics module.

Adding an orthodontic treatment (braces, aligners, retainer...) to a
patient — from a treatment plan or straight on the chart — opens an
orthodontic case when the patient has none open, so the treatment shows
up in the Orthodontics section without a second manual step.

Own-session (ADR 0019): ``odontogram.treatment.added`` is published
without the request session, and a missing case must never fail the
treatment that triggered it. Catalog data is read with plain SQL so this
module keeps no import of the catalog module.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import select, text

from app.database import async_session_maker

from .models import OrthoCase
from .schemas import OrthoCaseCreate
from .service import OrthoCaseService

logger = logging.getLogger(__name__)

ORTHO_CATEGORY_KEY = "ortodoncia"

# Catalog code -> appliance of the case it starts. Ortho items not listed
# here (custom clinic items) start a metal-brackets case; support items in
# NOT_A_CASE_START never open a case on their own.
APPLIANCE_BY_CODE: dict[str, str] = {
    "ORTO-METAL": "brackets_metal",
    "ORTO-BRACK": "brackets_metal",
    "ORTO-BRACK-CEMENT": "brackets_metal",
    "ORTO-CERAM": "brackets_esthetic",
    "ORTO-LINGUAL": "brackets_esthetic",
    "ORTO-INV-FULL": "aligners",
    "ORTO-INV-LITE": "aligners",
    "ORTO-ATTACH": "aligners",
    "ORTO-PALATAL-EXP": "functional",
    "ORTO-RET-FIX": "retention",
    "ORTO-RET-REM": "retention",
}
NOT_A_CASE_START = frozenset({"ORTO-REVIEW", "ORTO-SEPARATOR", "ORTO-TAD", "ORTO-BRACK-DEBOND"})

OPEN_STATUSES = ("active", "paused")


def _uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except ValueError:
        return None


def appliance_for(internal_code: str) -> str | None:
    """Appliance of the case an orthodontic catalog item starts, or None."""
    if internal_code in NOT_A_CASE_START:
        return None
    return APPLIANCE_BY_CODE.get(internal_code, "brackets_metal")


async def on_treatment_added(data: dict[str, Any]) -> None:
    clinic_id = _uuid(data.get("clinic_id"))
    patient_id = _uuid(data.get("patient_id"))
    catalog_item_id = _uuid(data.get("catalog_item_id"))
    if not (clinic_id and patient_id and catalog_item_id):
        return

    async with async_session_maker() as db:
        try:
            item = (
                await db.execute(
                    text(
                        "SELECT i.internal_code, i.names, c.key AS category_key "
                        "FROM treatment_catalog_items i "
                        "JOIN treatment_categories c ON c.id = i.category_id "
                        "WHERE i.id = :item_id AND i.clinic_id = :clinic_id"
                    ),
                    {"item_id": catalog_item_id, "clinic_id": clinic_id},
                )
            ).first()
            if item is None or item.category_key != ORTHO_CATEGORY_KEY:
                return
            appliance = appliance_for(item.internal_code)
            if appliance is None:
                return

            open_case = await db.scalar(
                select(OrthoCase.id).where(
                    OrthoCase.clinic_id == clinic_id,
                    OrthoCase.patient_id == patient_id,
                    OrthoCase.status.in_(OPEN_STATUSES),
                )
            )
            if open_case is not None:
                return

            names = item.names or {}
            label = names.get("en") or next(iter(names.values()), item.internal_code)
            await OrthoCaseService.create(
                db,
                clinic_id,
                OrthoCaseCreate(
                    patient_id=patient_id,
                    appliance_type=appliance,
                    start_date=date.today(),
                    diagnosis_notes=f"Opened automatically from the treatment plan: {label}",
                ),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception(
                "orthodontics: could not open a case for patient %s (catalog item %s)",
                patient_id,
                catalog_item_id,
            )
