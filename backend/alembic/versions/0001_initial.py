"""initial schema

Revision ID: 0001
Revises:
"""

from alembic import op

from firewatch.db.models import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    Base.metadata.create_all(op.get_bind())
    op.execute("CREATE INDEX IF NOT EXISTS ix_hotspots_cell ON hotspots (epsg, x_utm, y_utm)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_hotspots_code_time ON hotspots (code, acquired_at)")


def downgrade() -> None:
    Base.metadata.drop_all(op.get_bind())
