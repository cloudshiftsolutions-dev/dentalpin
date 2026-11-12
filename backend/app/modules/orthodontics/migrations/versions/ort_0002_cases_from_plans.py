"""Open orthodontic cases for patients who already have orthodontic treatments.

From this release, adding an orthodontic treatment opens a case
automatically (``events.on_treatment_added``). Patients whose
braces/aligners were planned before that get the same case here, so the
Orthodontics section is consistent for old and new plans. Data-only: the
codes mirror ``events.APPLIANCE_BY_CODE`` / ``NOT_A_CASE_START`` as they
were when this ran.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "ort_0002"
down_revision: str | None = "ort_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APPLIANCE_BY_CODE = {
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
_NOT_A_CASE_START = ("ORTO-REVIEW", "ORTO-SEPARATOR", "ORTO-TAD", "ORTO-BRACK-DEBOND")


def upgrade() -> None:
    bind = op.get_bind()
    tables_present = bind.execute(
        sa.text(
            "SELECT to_regclass('treatments') IS NOT NULL "
            "AND to_regclass('treatment_catalog_items') IS NOT NULL "
            "AND to_regclass('treatment_categories') IS NOT NULL"
        )
    ).scalar()
    if not tables_present:
        return

    appliance_case = "CASE i.internal_code " + " ".join(
        f"WHEN '{code}' THEN '{appliance}'" for code, appliance in _APPLIANCE_BY_CODE.items()
    )
    appliance_case += " ELSE 'brackets_metal' END"
    excluded = ", ".join(f"'{code}'" for code in _NOT_A_CASE_START)

    bind.execute(
        sa.text(
            f"""
            INSERT INTO ortho_cases
                (id, clinic_id, patient_id, appliance_type, status, start_date, diagnosis_notes)
            SELECT gen_random_uuid(), x.clinic_id, x.patient_id, x.appliance, 'active',
                   CURRENT_DATE,
                   'Opened automatically from the treatment plan: ' || x.label
            FROM (
                SELECT DISTINCT ON (t.clinic_id, t.patient_id)
                       t.clinic_id, t.patient_id,
                       {appliance_case} AS appliance,
                       COALESCE(i.names ->> 'en', i.internal_code) AS label
                FROM treatments t
                JOIN treatment_catalog_items i ON i.id = t.catalog_item_id
                JOIN treatment_categories c ON c.id = i.category_id
                WHERE c.key = 'ortodoncia'
                  AND t.deleted_at IS NULL
                  AND i.internal_code NOT IN ({excluded})
                ORDER BY t.clinic_id, t.patient_id, t.created_at
            ) x
            WHERE NOT EXISTS (
                SELECT 1 FROM ortho_cases o
                WHERE o.clinic_id = x.clinic_id
                  AND o.patient_id = x.patient_id
                  AND o.status IN ('active', 'paused')
            )
            """
        )
    )


def downgrade() -> None:
    # Data-only backfill: the cases may have controls by now, keep them.
    pass
