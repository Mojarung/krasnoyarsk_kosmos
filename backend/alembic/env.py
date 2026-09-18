import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from firewatch.config import get_settings
from firewatch.db.models import Base

target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    return not (type_ == "table" and name in {"spatial_ref_sys"})


def run_sync(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, include_object=include_object)
    with context.begin_transaction():
        context.run_migrations()


async def run_async() -> None:
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as connection:
        await connection.run_sync(run_sync)
    await engine.dispose()


asyncio.run(run_async())
