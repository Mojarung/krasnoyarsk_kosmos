from faststream.rabbit import RabbitBroker, RabbitQueue

from firewatch.config import get_settings

INGEST_QUEUE = RabbitQueue("scene.ingest", durable=True)
ACQUIRE_QUEUE = RabbitQueue("scene.acquire", durable=True)
VEGETATION_QUEUE = RabbitQueue("vegetation.observe", durable=True)

broker = RabbitBroker(get_settings().rabbit_url)


async def enqueue_ingest(job_id: str, scene_id: str) -> None:
    await broker.publish({"job_id": job_id, "scene_id": scene_id}, queue=INGEST_QUEUE, persist=True)


async def enqueue_acquire(job_id: str, scene_id: str) -> None:
    await broker.publish({"job_id": job_id, "scene_id": scene_id}, queue=ACQUIRE_QUEUE, persist=True)
