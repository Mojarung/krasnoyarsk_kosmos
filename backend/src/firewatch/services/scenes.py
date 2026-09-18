from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from firewatch.db.models import Job, Scene
from firewatch.infra.broker import enqueue_ingest
from firewatch.infra.cache import publish_event

AF_ROLES = ("viirs", "aux")
BS_ROLES = ("s2_pre", "s2_post", "s1_pre", "s1_post", "aux")
OPTIONAL_ROLES = ("mask",)


def required_roles(kind: str) -> tuple[str, ...]:
    return AF_ROLES if kind == "af" else BS_ROLES


def raw_key(kind: str, scene_id: str, role: str) -> str:
    return f"raw/{kind}/{scene_id}/{role}.tif"


async def register_scene(session: AsyncSession, values: dict[str, Any]) -> uuid.UUID:
    """Создаёт или обновляет сцену, заводит задание и ставит его в очередь."""
    statement = pg_insert(Scene).values(**values, status="queued")
    statement = statement.on_conflict_do_update(
        index_elements=[Scene.id],
        set_={k: statement.excluded[k] for k in values if k != "id"} | {"status": "queued"},
    )
    await session.execute(statement)
    job = Job(scene_id=values["id"])
    session.add(job)
    await session.commit()
    await enqueue_ingest(str(job.id), values["id"])
    await publish_event(
        "job",
        {
            "id": str(job.id),
            "scene_id": values["id"],
            "status": "queued",
            "stage": "queued",
            "progress": 0.0,
            "message": "В очереди RabbitMQ",
        },
    )
    return job.id
