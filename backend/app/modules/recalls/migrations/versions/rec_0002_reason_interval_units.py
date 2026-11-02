"""recalls: per-reason interval unit (day / week / month).

DENTALPIN-13. Default recall intervals were whole months only, so a
clinic could not configure a recall shorter than one month. The count
stays in ``reason_intervals``; this column records its unit. Existing
rows get ``{}``, which reads as months, so their behaviour is unchanged.

Revision ID: rec_0002
Revises: rec_0001
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "rec_0002"
down_revision: str | None = "rec_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "recall_settings",
        sa.Column(
            "reason_interval_units",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    # Drop the server default so application code controls future inserts.
    op.alter_column("recall_settings", "reason_interval_units", server_default=None)


def downgrade() -> None:
    op.drop_column("recall_settings", "reason_interval_units")
