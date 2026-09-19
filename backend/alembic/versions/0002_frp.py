"""мощность излучения пожара у термоточки

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE hotspots ADD COLUMN IF NOT EXISTS frp_mw double precision")


def downgrade() -> None:
    op.execute("ALTER TABLE hotspots DROP COLUMN IF EXISTS frp_mw")
