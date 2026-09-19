from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from firewatch.config import get_settings

log = logging.getLogger(__name__)

DATA_VERSION_KEY = "fw:data_version"
EVENTS_CHANNEL = "fw:events"

redis = Redis.from_url(get_settings().redis_url)


def make_key(prefix: str, payload: Any) -> str:
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:24]
    return f"fw:{prefix}:{digest}"


async def bump_data_version() -> None:
    await redis.incr(DATA_VERSION_KEY)


async def cached[T](
    prefix: str,
    payload: Any,
    producer: Callable[[], Awaitable[T]],
    *,
    binary: bool = False,
    versioned: bool = True,
    ttl: int | None = None,
) -> T:
    """Кеш поверх Redis. Версия данных входит в ключ, поэтому после приёма новой сцены кеш не отдаёт старое.

    versioned=False нужен внешним справочникам: дороги и архив погоды от наших сцен не зависят.
    """
    try:
        version = (await redis.get(DATA_VERSION_KEY) or b"0").decode() if versioned else "static"
        key = make_key(prefix, [version, payload])
        hit = await redis.get(key)
    except RedisError:
        log.warning("Redis недоступен, запрос идёт мимо кеша", exc_info=True)
        return await producer()
    if hit is not None:
        return hit if binary else json.loads(hit)
    value = await producer()
    raw = value if binary else json.dumps(value, default=str)
    try:
        await redis.set(key, raw, ex=ttl or get_settings().cache_ttl_seconds)
    except RedisError:
        log.warning("Не удалось записать в кеш", exc_info=True)
    return value


async def peek(prefix: str, payload: Any) -> Any | None:
    """Чтение без версии данных и без расчёта при промахе. RedisError уходит наверх: вызывающий решает, что делать без кеша."""
    hit = await redis.get(make_key(prefix, ["static", payload]))
    return None if hit is None else json.loads(hit)


async def put(prefix: str, payload: Any, value: Any, ttl: int) -> None:
    await redis.set(make_key(prefix, ["static", payload]), json.dumps(value, default=str), ex=ttl)


async def publish_event(event: str, data: dict[str, Any]) -> None:
    await redis.publish(EVENTS_CHANNEL, json.dumps({"event": event, "data": data}, default=str))


async def subscribe_events() -> AsyncIterator[dict[str, Any]]:
    pubsub = redis.pubsub()
    await pubsub.subscribe(EVENTS_CHANNEL)
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                yield json.loads(message["data"])
    finally:
        await pubsub.unsubscribe(EVENTS_CHANNEL)
        await pubsub.aclose()
