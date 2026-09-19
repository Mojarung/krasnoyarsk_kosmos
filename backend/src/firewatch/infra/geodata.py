"""Внешние справочники для плана реагирования: ветер из Open-Meteo, окружение очага из OpenStreetMap.

Оба источника необязательны. Если сеть недоступна, функции возвращают None, и карточка строится без них.
"""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from redis.exceptions import RedisError
from shapely.geometry import LineString, Point

from firewatch.config import get_settings
from firewatch.infra.cache import cached, peek, put

log = logging.getLogger(__name__)

# Дубли фоновых запросов отсекаются внутри процесса. API работает одним процессом uvicorn; при нескольких
# процессах замок нужно перенести в Redis (SET NX), иначе Overpass получит одинаковые запросы.
_inflight: set[tuple[float, float, float]] = set()
_tasks: set[asyncio.Task[None]] = set()

SETTLEMENT_REACH_STEP_KM = 5
SETTLEMENT_REACH_MAX_KM = 30
STATION_RADIUS_M = 50_000
WATER_RADIUS_M = 10_000
# Дальше трёх километров подъезд уже считается затруднённым, искать дороги шире незачем.
ROAD_RADIUS_M = 3_000
OVERPASS_TIMEOUT_SECONDS = 90
ARCHIVE_DELAY = timedelta(days=7)
KM_PER_DEGREE = 111.32
USER_AGENT = "firewatch-hackathon/0.1"

OVERPASS_RETRY_SECONDS = 6.0
OVERPASS_PAUSE_SECONDS = 2.0
OSM_FAILURE_TTL_SECONDS = 180
RETRYABLE_STATUS = frozenset({429, 502, 503, 504})

_PLACES = 'node[place~"^(city|town|village|hamlet)$"][name](around:{radius},{lat},{lon});'
_STATIONS = "nwr[amenity=fire_station](around:{radius},{lat},{lon});"
_WATER = (
    "nwr[natural=water][name](around:{radius},{lat},{lon});"
    'way[waterway~"^(river|canal)$"][name](around:{radius},{lat},{lon});'
)
_ROADS = (
    'way[highway~"^(motorway|trunk|primary|secondary|tertiary|unclassified|track)$"]'
    "(around:{radius},{lat},{lon});"
)


def _rounded(lon: float, lat: float, digits: int) -> tuple[float, float]:
    """Округление ради попаданий в кеш: 0,01 градуса (около километра) для погоды, 0,001 для дорог."""
    return round(lon, digits), round(lat, digits)


async def _get_json(url: str, *, wait_seconds: float | None = None, **kwargs: Any) -> Any:
    limit = wait_seconds or get_settings().external_timeout_seconds
    async with httpx.AsyncClient(timeout=limit, headers={"User-Agent": USER_AGENT}) as client:
        response = await client.request(kwargs.pop("method", "GET"), url, **kwargs)
        response.raise_for_status()
        return response.json()


async def wind_at(lon: float, lat: float, moment: datetime) -> dict[str, float] | None:
    """Направление (откуда дует, градусы) и скорость ветра на 10 м в ближайший к пролёту час."""
    settings = get_settings()
    if not settings.external_lookups:
        return None
    moment = moment.astimezone(UTC)
    recent = datetime.now(UTC) - moment < ARCHIVE_DELAY
    url = settings.open_meteo_forecast_url if recent else settings.open_meteo_archive_url
    lon, lat = _rounded(lon, lat, 2)
    day = moment.date().isoformat()
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": day,
        "end_date": day,
        "hourly": "wind_direction_10m,wind_speed_10m",
        "wind_speed_unit": "ms",
        "timezone": "UTC",
    }

    async def produce() -> dict[str, float] | None:
        hourly = (await _get_json(url, params=params))["hourly"]
        hour = min(moment.hour + (moment.minute >= 30), len(hourly["time"]) - 1)
        direction, speed = hourly["wind_direction_10m"][hour], hourly["wind_speed_10m"][hour]
        return (
            None
            if direction is None
            else {"direction_deg": float(direction), "speed_ms": float(speed or 0.0)}
        )

    try:
        return await cached(
            "wind",
            [lon, lat, day, moment.hour],
            produce,
            versioned=False,
            ttl=settings.external_cache_seconds,
        )
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        log.warning("Open-Meteo не ответил для %s,%s на %s", lon, lat, day, exc_info=True)
        return None


def _position(element: dict[str, Any]) -> tuple[float, float] | None:
    source = element if "lon" in element else element.get("center")
    return (source["lon"], source["lat"]) if source else None


def _road_km(lon: float, lat: float, roads: list[dict[str, Any]]) -> float | None:
    """Расстояние до ближайшей дороги в локальной равнопромежуточной проекции: на 3 км ошибка меньше процента."""
    scale = math.cos(math.radians(lat))
    lines = [
        LineString(
            [
                ((p["lon"] - lon) * scale * KM_PER_DEGREE, (p["lat"] - lat) * KM_PER_DEGREE)
                for p in way["geometry"]
            ]
        )
        for way in roads
        if len(way.get("geometry", [])) >= 2
    ]
    return min((line.distance(Point(0.0, 0.0)) for line in lines), default=None)


def _place(element: dict[str, Any], kind: str, fallback: str) -> dict[str, Any] | None:
    position = _position(element)
    if position is None:
        return None
    tags = element.get("tags", {})
    return {
        "name": tags.get("name", fallback),
        "kind": tags.get("place", kind),
        "lon": position[0],
        "lat": position[1],
    }


def _within(places: list[dict[str, Any]], lon: float, lat: float, radius_km: float) -> list[dict[str, Any]]:
    scale = math.cos(math.radians(lat)) * KM_PER_DEGREE
    return [
        p
        for p in places
        if math.hypot((p["lon"] - lon) * scale, (p["lat"] - lat) * KM_PER_DEGREE) <= radius_km
    ]


def parse_overpass(
    points: list[tuple[float, float, float]], elements: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Ответ общий на все очаги. Каждому очагу достаются объекты в его радиусах: (lon, lat, reach_km)."""
    settlements, stations, water, roads = [], [], [], []
    for element in elements:
        tags = element.get("tags", {})
        # Дороги запрашиваются без тегов (out skel), их выдаёт наличие геометрии.
        if "geometry" in element:
            roads.append(element)
        elif tags.get("amenity") == "fire_station":
            stations.append(_place(element, "fire_station", "Пожарная часть"))
        elif "place" in tags:
            settlements.append(_place(element, "village", "Населённый пункт"))
        else:
            water.append(_place(element, "water", "Водоём"))

    result = []
    for lon, lat, reach_km in points:
        road_km = _road_km(lon, lat, roads)
        far = road_km is None or road_km > ROAD_RADIUS_M / 1000.0
        result.append(
            {
                "settlements": _within([p for p in settlements if p], lon, lat, reach_km),
                "fire_stations": _within([p for p in stations if p], lon, lat, STATION_RADIUS_M / 1000.0),
                "water": _within([p for p in water if p], lon, lat, WATER_RADIUS_M / 1000.0),
                # Дорог в радиусе поиска нет: честнее сказать «не ближе радиуса», чем «неизвестно».
                "road_km": ROAD_RADIUS_M / 1000.0 if far else road_km,
            }
        )
    return result


def overpass_query(points: list[tuple[float, float, float]], timeout: int) -> str:
    def block(template: str, radius_m: float | None = None) -> str:
        return "".join(
            template.format(radius=int(radius_m or reach_km * 1000), lat=lat, lon=lon)
            for lon, lat, reach_km in points
        )

    return (
        f"[out:json][timeout:{timeout}];"
        f"({block(_PLACES)})->.places;({block(_STATIONS, STATION_RADIUS_M)})->.stations;"
        f"({block(_WATER, WATER_RADIUS_M)})->.water;({block(_ROADS, ROAD_RADIUS_M)})->.roads;"
        ".places out; .stations out center; .water out center 120; .roads out skel geom;"
    )


async def _ask_overpass(body: str) -> list[dict[str, Any]]:
    """Публичные серверы Overpass режут частые запросы, поэтому зеркала перебираются по очереди с одной паузой."""
    failure: Exception | None = None
    for attempt, url in enumerate(get_settings().overpass_urls):
        if attempt:
            await asyncio.sleep(OVERPASS_RETRY_SECONDS)
        try:
            payload = await _get_json(
                url, wait_seconds=OVERPASS_TIMEOUT_SECONDS, method="POST", data={"data": body}
            )
            return payload["elements"]
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in RETRYABLE_STATUS:
                raise
            failure = exc
        except httpx.TransportError as exc:
            failure = exc
        log.warning("Overpass %s не ответил: %s", url, failure)
    raise failure or httpx.TransportError("Список серверов Overpass пуст")


def reach_step(reach_km: float) -> int:
    steps = math.ceil(max(reach_km, 1.0) / SETTLEMENT_REACH_STEP_KM)
    return min(steps * SETTLEMENT_REACH_STEP_KM, SETTLEMENT_REACH_MAX_KM)


async def _fetch_in_background(points: list[tuple[float, float, float]]) -> None:
    """Очаги спрашиваются по одному: общий запрос на все сразу публичный сервер не успевает выполнить."""
    settings = get_settings()
    for index, point in enumerate(points):
        if index:
            await asyncio.sleep(OVERPASS_PAUSE_SECONDS)
        try:
            elements = await _ask_overpass(overpass_query([point], OVERPASS_TIMEOUT_SECONDS))
            await put(
                "osm", point, {"data": parse_overpass([point], elements)[0]}, settings.external_cache_seconds
            )
        except (httpx.HTTPError, KeyError, ValueError, RedisError):
            log.warning("OpenStreetMap не ответил для %s", point, exc_info=True)
            try:
                await put("osm", point, {"data": None}, OSM_FAILURE_TTL_SECONDS)
            except RedisError:
                log.warning("Не удалось записать в кеш", exc_info=True)
        finally:
            _inflight.discard(point)


async def surroundings(points: list[tuple[float, float, float]]) -> tuple[list[dict[str, Any] | None], str]:
    """Окружение очагов из кеша плюс статус: ready, pending, failed или off.

    Публичный Overpass отвечает от секунды до минуты, поэтому запрос плана его не ждёт: промахи уходят
    в фоновую задачу, а клиент переспрашивает план, пока статус pending.
    points: (lon, lat, reach_km), где reach_km - докуда фронт дойдёт за самый дальний горизонт прогноза.
    """
    if not get_settings().external_lookups or not points:
        return [None] * len(points), "off"
    rounded = [(*_rounded(lon, lat, 3), float(reach_step(reach))) for lon, lat, reach in points]
    try:
        hits = [await peek("osm", point) for point in rounded]
    except RedisError:
        log.warning("Redis недоступен, окружение очагов не запрашивается", exc_info=True)
        return [None] * len(points), "failed"

    missing = [
        point for point, hit in zip(rounded, hits, strict=True) if hit is None and point not in _inflight
    ]
    if missing:
        _inflight.update(missing)
        task = asyncio.create_task(_fetch_in_background(missing))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    found = [hit["data"] if hit else None for hit in hits]
    if any(hit is None for hit in hits):
        return found, "pending"
    return found, "ready" if all(item is not None for item in found) else "failed"
