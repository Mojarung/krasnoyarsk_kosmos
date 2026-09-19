"""Анализ произвольной области по свежим открытым снимкам: заявка, подсказка области, постановка в очередь."""

from __future__ import annotations

import json
import random
import uuid
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from importlib import resources
from typing import Any

from geoalchemy2.shape import from_shape
from pyproj import Transformer
from shapely.geometry import Point, box, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from firewatch.config import get_settings
from firewatch.db.models import Job, Scene
from firewatch.infra.broker import enqueue_acquire
from firewatch.infra.cache import publish_event
from firewatch.pipeline.acquire import CHIP_M, WGS84, AreaTooLargeError, ChipGrid, plan_grids, utm_epsg

# Sentinel-2 L2A в каталоге начинается с 2017 года, а свежая сцена появляется через несколько дней после съёмки.
ARCHIVE_START = date(2017, 4, 1)
PUBLICATION_LAG = timedelta(days=5)
MIN_GAP = timedelta(days=5)
MAX_GAP = timedelta(days=120)
DEFAULT_GAP = timedelta(days=30)
FIRE_PRE_GAP = timedelta(days=12)
FIRE_POST_GAP = timedelta(days=8)
MIN_FIRE_HOTSPOTS = 5
SAMPLE_ATTEMPTS = 200

_RANDOM_FIRE = text(
    """
    SELECT ST_X(ST_Centroid(ST_Collect(geom))) AS lon, ST_Y(ST_Centroid(ST_Collect(geom))) AS lat,
           acquired_at::date AS day, count(*) AS hotspots
    FROM hotspots WHERE code = 1 AND NOT persistent
    GROUP BY scene_id, acquired_at::date HAVING count(*) >= :min_hotspots
    ORDER BY random() LIMIT 1
    """
)


class InvalidAcquisitionError(ValueError):
    pass


@lru_cache
def _aoi() -> BaseGeometry:
    raw = json.loads(resources.files("firewatch.assets").joinpath("aoi.geojson").read_text("utf-8"))
    feature = raw["features"][0] if raw.get("type") == "FeatureCollection" else raw
    return shape(feature.get("geometry", feature))


def chip_square(lon: float, lat: float) -> BaseGeometry:
    """Квадрат размером с один чип вокруг точки, в WGS 84."""
    epsg = utm_epsg(lon, lat)
    x, y = Transformer.from_crs(WGS84, epsg, always_xy=True).transform(lon, lat)
    half = CHIP_M / 2.0
    to_wgs84 = Transformer.from_crs(epsg, WGS84, always_xy=True).transform
    return shapely_transform(to_wgs84, box(x - half, y - half, x + half, y + half))


def validate_dates(date_pre: date, date_post: date, today: date) -> None:
    if date_pre < ARCHIVE_START:
        raise InvalidAcquisitionError(f"Снимки Sentinel-2 L2A в каталоге есть с {ARCHIVE_START:%d.%m.%Y}")
    if date_post > today - PUBLICATION_LAG:
        raise InvalidAcquisitionError(
            f"Дата «после» не позже {today - PUBLICATION_LAG:%d.%m.%Y}: сцена попадает в каталог через несколько дней"
        )
    gap = date_post - date_pre
    if gap < MIN_GAP or gap > MAX_GAP:
        raise InvalidAcquisitionError(
            f"Между снимками «до» и «после» должно быть от {MIN_GAP.days} до {MAX_GAP.days} дней"
        )


def random_point(rng: random.Random) -> Point:
    aoi = _aoi()
    west, south, east, north = aoi.bounds
    for _ in range(SAMPLE_ATTEMPTS):
        point = Point(rng.uniform(west, east), rng.uniform(south, north))
        if aoi.contains(point):
            return point
    return aoi.representative_point()


async def suggest(session: AsyncSession, mode: str) -> dict[str, Any]:
    today = datetime.now(UTC).date()
    if mode == "fire":
        row = (await session.execute(_RANDOM_FIRE, {"min_hotspots": MIN_FIRE_HOTSPOTS})).mappings().first()
        if row is not None:
            return {
                "mode": "fire",
                "geometry": mapping(chip_square(row["lon"], row["lat"])),
                "date_pre": (row["day"] - FIRE_PRE_GAP).isoformat(),
                "date_post": (row["day"] + FIRE_POST_GAP).isoformat(),
                "label": f"Очаг {row['day']:%d.%m.%Y}, {row['hotspots']} термоточек VIIRS",
            }
    point = random_point(random.Random())
    date_post = today - PUBLICATION_LAG - timedelta(days=2)
    return {
        "mode": "random",
        "geometry": mapping(chip_square(point.x, point.y)),
        "date_pre": (date_post - DEFAULT_GAP).isoformat(),
        "date_post": date_post.isoformat(),
        "label": f"Случайная точка {point.y:.3f}, {point.x:.3f}",
    }


def _scene_values(grid: ChipGrid, date_pre: date, date_post: date) -> dict[str, Any]:
    west, _, _, north = grid.bounds
    return {
        "id": f"BS_live_{uuid.uuid4().hex[:8]}",
        "kind": "bs",
        "source": "live",
        "status": "queued",
        "epsg": grid.epsg,
        "footprint": from_shape(grid.footprint_wgs84(), srid=WGS84),
        "date_pre": date_pre,
        "date_post": date_post,
        "files": {},
        "stats": {
            "acquisition": {
                "epsg": grid.epsg,
                "origin": [west, north],
                "requested": [date_pre.isoformat(), date_post.isoformat()],
            }
        },
    }


async def request_acquisition(
    session: AsyncSession, area: BaseGeometry, date_pre: date, date_post: date
) -> list[dict[str, str]]:
    validate_dates(date_pre, date_post, datetime.now(UTC).date())
    try:
        grids = plan_grids(area, get_settings().live_max_chips)
    except AreaTooLargeError as exc:
        raise InvalidAcquisitionError(str(exc)) from exc
    created = []
    for grid in grids:
        values = _scene_values(grid, date_pre, date_post)
        session.add(Scene(**values))
        # Между моделями нет relationship, и без явного flush задание может уйти в базу раньше своей сцены.
        await session.flush()
        job = Job(scene_id=values["id"])
        session.add(job)
        await session.flush()
        created.append({"job_id": str(job.id), "scene_id": values["id"]})
    await session.commit()

    for item in created:
        await enqueue_acquire(item["job_id"], item["scene_id"])
        await publish_event(
            "job",
            {
                "id": item["job_id"],
                "scene_id": item["scene_id"],
                "status": "queued",
                "stage": "queued",
                "progress": 0.0,
                "message": "В очереди RabbitMQ",
            },
        )
    return created
