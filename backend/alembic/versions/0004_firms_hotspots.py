"""deduplicate hotspots imported from NASA FIRMS

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE hotspots ADD COLUMN IF NOT EXISTS external_id varchar(64)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_hotspots_external_id "
        "ON hotspots (external_id) WHERE external_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_hotspots_external_id")
    op.execute("ALTER TABLE hotspots DROP COLUMN IF EXISTS external_id")
