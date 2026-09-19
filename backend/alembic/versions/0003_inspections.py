"""Сохранённые задания на осмотр, неизменяемые карточки по секретной ссылке."""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE inspections (
            id uuid PRIMARY KEY,
            share_token varchar(64) NOT NULL UNIQUE,
            event_id varchar(80) NOT NULL,
            purpose varchar(32) NOT NULL,
            note text NOT NULL,
            site jsonb NOT NULL,
            access jsonb,
            snapshot jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.create_index("ix_inspections_event_id", "inspections", ["event_id"])


def downgrade() -> None:
    op.drop_table("inspections")
