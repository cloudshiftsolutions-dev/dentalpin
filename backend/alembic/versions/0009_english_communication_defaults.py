"""core — CloudShift fork: English as the communication language everywhere.

Upstream defaults patient-facing language to Spanish (``es``). This fork
serves English-speaking clinics, so existing Spanish settings are moved
to English: the clinic communication language (emails, WhatsApp, PDFs,
timeline titles), patient and notification-preference languages, and
the language stored on prescriptions (used when a PDF is re-rendered).

Module tables are optional (a module may be uninstalled), so each update
runs only when its table exists. The previous language isn't recorded,
so downgrade is a no-op.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, column) holding a plain language code.
_LANGUAGE_COLUMNS = (
    ("patients", "preferred_language"),
    ("notification_preferences", "preferred_locale"),
    ("prescriptions", "locale"),
)


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    return bind.execute(sa.text("SELECT to_regclass(:t) IS NOT NULL"), {"t": table}).scalar()


def upgrade() -> None:
    op.execute(
        """
        UPDATE clinics
        SET settings = jsonb_set(
            COALESCE(settings, '{}'::jsonb), '{communication_language}', '"en"'::jsonb, true
        )
        WHERE COALESCE(settings->>'communication_language', 'es') = 'es'
        """
    )
    for table, column in _LANGUAGE_COLUMNS:
        if _table_exists(table):
            op.execute(f"UPDATE {table} SET {column} = 'en' WHERE {column} = 'es'")


def downgrade() -> None:
    pass
