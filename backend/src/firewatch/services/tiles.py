from __future__ import annotations

import asyncio
import json
import logging
import math
from functools import lru_cache
from importlib import resources

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from firewatch.db.session import SessionFactory
from firewatch.infra.cache import cached

log = logging.getLogger(__name__)

SEVERITY_MIN_ZOOM = 10
MAX_ZOOM = 16
TILE_EXTENT = 4096
# Генерализация по зуму: объект меньше экранного пикселя не виден, но стоит времени и трафика.
# Пороги площади, га: контуры гарей и полигоны степеней.
MIN_CONTOUR_HA = {5: 100.0, 6: 50.0, 7: 20.0, 8: 5.0, 9: 1.0}
MIN_SEVERITY_HA = {10: 1.0, 11: 0.2}

_EPOCH_DAYS = "({col} - DATE '1970-01-01')"

_CONTOURS = text(
    f"""
    WITH bounds AS (
        SELECT ST_TileEnvelope(:z, :x, :y) AS merc, ST_Transform(ST_TileEnvelope(:z, :x, :y), 4326) AS wgs
    ), area AS (
        SELECT CASE WHEN :clip = '' THEN NULL ELSE ST_SetSRID(ST_GeomFromGeoJSON(:clip), 4326) END AS geom
    ), contours AS (
        SELECT b.id, b.scene_id, b.area_ha, b.sev1_ha, b.sev2_ha, b.sev3_ha,
               {_EPOCH_DAYS.format(col="b.date_pre")} AS t0, {_EPOCH_DAYS.format(col="b.date_post")} AS t1,
               ST_AsMVTGeom(ST_Transform(ST_Simplify(b.geom, :tolerance), 3857), bounds.merc, 4096, 64, true) AS geom
        FROM burn_areas b, bounds, area
        WHERE b.geom && bounds.wgs AND b.area_ha >= :min_contour_ha
          AND (area.geom IS NULL OR ST_Intersects(b.geom, area.geom))
    ), centers AS (
        SELECT b.id, b.scene_id, b.area_ha,
               {_EPOCH_DAYS.format(col="b.date_pre")} AS t0, {_EPOCH_DAYS.format(col="b.date_post")} AS t1,
               ST_AsMVTGeom(ST_Transform(ST_PointOnSurface(b.geom), 3857), bounds.merc, 4096, 0, true) AS geom
        FROM burn_areas b, bounds, area
        WHERE b.geom && bounds.wgs
          AND ST_PointOnSurface(b.geom) && bounds.wgs AND b.area_ha >= :min_center_ha
          AND (area.geom IS NULL OR ST_Intersects(b.geom, area.geom))
    )
    SELECT coalesce((SELECT ST_AsMVT(contours, 'contours', 4096, 'geom', 'id') FROM contours WHERE geom IS NOT NULL), '')
        || coalesce((SELECT ST_AsMVT(centers, 'centers', 4096, 'geom', 'id') FROM centers WHERE geom IS NOT NULL), '')
    """
)

_SEVERITY = text(
    f"""
    WITH bounds AS (
        SELECT ST_TileEnvelope(:z, :x, :y) AS merc, ST_Transform(ST_TileEnvelope(:z, :x, :y), 4326) AS wgs
    ), area AS (
        SELECT CASE WHEN :clip = '' THEN NULL ELSE ST_SetSRID(ST_GeomFromGeoJSON(:clip), 4326) END AS geom
    ), tile_rows AS (
        SELECT s.id, s.severity, s.scene_id, s.burn_area_id AS contour_id, s.area_ha, b.area_ha AS contour_ha,
               {_EPOCH_DAYS.format(col="sc.date_pre")} AS t0, {_EPOCH_DAYS.format(col="s.date_post")} AS t1,
               ST_AsMVTGeom(ST_Transform(s.geom, 3857), bounds.merc, 4096, 64, true) AS geom
        FROM severity_polygons s
        JOIN scenes sc ON sc.id = s.scene_id
        JOIN burn_areas b ON b.id = s.burn_area_id, bounds, area
        WHERE s.geom && bounds.wgs AND s.area_ha >= :min_severity_ha
          AND (area.geom IS NULL OR ST_Intersects(s.geom, area.geom))
    )
    SELECT coalesce((SELECT ST_AsMVT(tile_rows, 'severity', 4096, 'geom', 'id') FROM tile_rows WHERE geom IS NOT NULL), '')
    """
)


def _min_center_ha(z: int) -> float:
    return 200.0 if z <= 5 else 50.0 if z <= 7 else 0.0


def _tolerance_deg(z: int) -> float:
    """Допуск упрощения: один шаг сетки тайла в градусах. С 12-го зума контур идёт без упрощения."""
    return 0.0 if z >= 12 else 360.0 / (2**z) / TILE_EXTENT


# Ограничение выдачи выбранной областью. В адресе тайла лежит короткий ключ:
# '' или 'aoi' - без ограничения, '<id региона>' - геометрия из ассета,
# 'p:lon,lat;...' - нарисованный пользователем контур (он маленький и в адрес влезает).
CUSTOM_PREFIX = "p:"
MAX_CUSTOM_POINTS = 500


@lru_cache
def _regions() -> dict[str, str]:
    raw = json.loads(resources.files("firewatch.assets").joinpath("regions.geojson").read_text("utf-8"))
    return {f["properties"]["id"]: json.dumps(f["geometry"]) for f in raw["features"]}


def _custom_polygon(value: str) -> str:
    ring: list[list[float]] = []
    for pair in value.split(";"):
        lon, _, lat = pair.partition(",")
        ring.append([round(float(lon), 6), round(float(lat), 6)])
    if not 3 <= len(ring) <= MAX_CUSTOM_POINTS:
        raise ValueError("Контур должен содержать от 3 до 500 точек")
    if any(not -180 <= lon <= 180 or not -90 <= lat <= 90 for lon, lat in ring):
        raise ValueError("Координаты контура вне допустимых границ")
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return json.dumps({"type": "Polygon", "coordinates": [ring]})


def clip_geojson(clip: str | None) -> str:
    """Ключ области из адреса тайла в геометрию для SQL. Пустая строка - без ограничения."""
    if not clip or clip == "aoi":
        return ""
    if clip.startswith(CUSTOM_PREFIX):
        try:
            return _custom_polygon(clip[len(CUSTOM_PREFIX) :])
        except ValueError as exc:
            raise ValueError(f"Неверный контур области: {exc}") from exc
    geometry = _regions().get(clip)
    if geometry is None:
        raise ValueError(f"Неизвестная область: {clip}")
    return geometry


async def render_tile(session: AsyncSession, z: int, x: int, y: int, clip: str = "") -> bytes:
    params = {"z": z, "x": x, "y": y, "clip": clip}
    contour_params = params | {
        "min_center_ha": _min_center_ha(z),
        "min_contour_ha": MIN_CONTOUR_HA.get(max(z, min(MIN_CONTOUR_HA)), 0.0),
        "tolerance": _tolerance_deg(z),
    }
    tile = bytes((await session.execute(_CONTOURS, contour_params)).scalar_one())
    if z >= SEVERITY_MIN_ZOOM:
        severity_params = params | {"min_severity_ha": MIN_SEVERITY_HA.get(z, 0.0)}
        tile += bytes((await session.execute(_SEVERITY, severity_params)).scalar_one())
    return tile


WARM_ZOOMS = (10, 11)
WARM_CONCURRENCY = 2
# Shared across reports: one semaphore per call multiplied background load
# on every territory change, starving interactive queries of connections.
_warm_gate = asyncio.Semaphore(WARM_CONCURRENCY)
_render_gate = asyncio.Semaphore(4)


def tile_of(lon: float, lat: float, z: int) -> tuple[int, int]:
    n = 2**z
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


async def cached_tile(session: AsyncSession, z: int, x: int, y: int, clip: str = "") -> bytes:
    async def produce() -> bytes:
        async with _render_gate:
            return await render_tile(session, z, x, y, clip)

    return await cached("tile", [z, x, y, clip], produce, binary=True)


async def warm_tiles(points: list[tuple[float, float]]) -> None:
    """Заранее кладёт в кеш тайлы вокруг точек, к которым пользователь вероятно перелетит."""
    wanted = {
        (z, x + dx, y + dy)
        for lon, lat in points
        for z in WARM_ZOOMS
        for x, y in [tile_of(lon, lat, z)]
        for dx in (-1, 0, 1)
        for dy in (-1, 0, 1)
    }

    async def warm(z: int, x: int, y: int) -> None:
        async with _warm_gate, SessionFactory() as session:
            await cached_tile(session, z, x, y)

    results = await asyncio.gather(*(warm(*tile) for tile in wanted), return_exceptions=True)
    failed = [r for r in results if isinstance(r, Exception)]
    if failed:
        log.warning(
            "Прогрев тайлов: %s из %s не удалось, первая ошибка: %r", len(failed), len(wanted), failed[0]
        )
