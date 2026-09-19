"""Сохранённые задания на осмотр, неизменяемые карточки по секретной ссылке."""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 создаёт таблицы по текущим моделям, поэтому на чистой базе inspections уже есть.
    op.execute("""
        CREATE TABLE IF NOT EXISTS inspections (
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
    op.execute("CREATE INDEX IF NOT EXISTS ix_inspections_event_id ON inspections (event_id)")


def downgrade() -> None:
    op.drop_table("inspections")
