import asyncio
import logging
import uuid

from faststream import FastStream
from faststream.rabbit import Channel
from pydantic import BaseModel

from firewatch.config import get_settings
from firewatch.infra import s3
from firewatch.infra.broker import ACQUIRE_QUEUE, INGEST_QUEUE, broker
from firewatch.pipeline.acquire_job import acquire_scene
from firewatch.pipeline.ingest import process_scene

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


class IngestMessage(BaseModel):
    job_id: uuid.UUID
    scene_id: str


app = FastStream(broker)


@app.on_startup
async def prepare_storage() -> None:
    s3.ensure_bucket()


@broker.subscriber(INGEST_QUEUE, channel=Channel(prefetch_count=get_settings().worker_prefetch))
async def ingest(message: IngestMessage) -> None:
    await process_scene(message.job_id, message.scene_id)


# Скачивание снимков идёт минутами, поэтому у него своя очередь: обычные сцены за ним не стоят.
@broker.subscriber(ACQUIRE_QUEUE, channel=Channel(prefetch_count=1))
async def acquire(message: IngestMessage) -> None:
    await acquire_scene(message.job_id, message.scene_id)


if __name__ == "__main__":
    asyncio.run(app.run())
