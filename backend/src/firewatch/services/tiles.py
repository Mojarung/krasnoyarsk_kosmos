from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SEVERITY_MIN_ZOOM = 9
MAX_ZOOM = 16

_EPOCH_DAYS = "({col} - DATE '1970-01-01')"

_CONTOURS = text(
    f"""
    WITH bounds AS (
        SELECT ST_TileEnvelope(:z, :x, :y) AS merc, ST_Transform(ST_TileEnvelope(:z, :x, :y), 4326) AS wgs
    ), contours AS (
        SELECT b.id, b.scene_id, b.area_ha, b.sev1_ha, b.sev2_ha, b.sev3_ha,
               {_EPOCH_DAYS.format(col="b.date_pre")} AS t0, {_EPOCH_DAYS.format(col="b.date_post")} AS t1,
               ST_AsMVTGeom(ST_Transform(b.geom, 3857), bounds.merc, 4096, 64, true) AS geom
        FROM burn_areas b, bounds WHERE b.geom && bounds.wgs
    ), centers AS (
        SELECT b.id, b.scene_id, b.area_ha,
               {_EPOCH_DAYS.format(col="b.date_pre")} AS t0, {_EPOCH_DAYS.format(col="b.date_post")} AS t1,
               ST_AsMVTGeom(ST_Transform(ST_PointOnSurface(b.geom), 3857), bounds.merc, 4096, 0, true) AS geom
        FROM burn_areas b, bounds WHERE ST_PointOnSurface(b.geom) && bounds.wgs AND b.area_ha >= :min_center_ha
    )
    SELECT coalesce((SELECT ST_AsMVT(contours, 'contours', 4096, 'geom', 'id') FROM contours WHERE geom IS NOT NULL), '')
        || coalesce((SELECT ST_AsMVT(centers, 'centers', 4096, 'geom', 'id') FROM centers WHERE geom IS NOT NULL), '')
    """
)

_SEVERITY = text(
    f"""
    WITH bounds AS (
        SELECT ST_TileEnvelope(:z, :x, :y) AS merc, ST_Transform(ST_TileEnvelope(:z, :x, :y), 4326) AS wgs
    ), tile_rows AS (
        SELECT s.id, s.severity, s.scene_id, s.burn_area_id AS contour_id, s.area_ha,
               {_EPOCH_DAYS.format(col="sc.date_pre")} AS t0, {_EPOCH_DAYS.format(col="s.date_post")} AS t1,
               ST_AsMVTGeom(ST_Transform(s.geom, 3857), bounds.merc, 4096, 64, true) AS geom
        FROM severity_polygons s JOIN scenes sc ON sc.id = s.scene_id, bounds
        WHERE s.geom && bounds.wgs
    )
    SELECT coalesce((SELECT ST_AsMVT(tile_rows, 'severity', 4096, 'geom', 'id') FROM tile_rows WHERE geom IS NOT NULL), '')
    """
)


def _min_center_ha(z: int) -> float:
    return 200.0 if z <= 5 else 50.0 if z <= 7 else 0.0


async def render_tile(session: AsyncSession, z: int, x: int, y: int) -> bytes:
    params = {"z": z, "x": x, "y": y}
    tile = bytes(
        (await session.execute(_CONTOURS, params | {"min_center_ha": _min_center_ha(z)})).scalar_one()
    )
    if z >= SEVERITY_MIN_ZOOM:
        tile += bytes((await session.execute(_SEVERITY, params)).scalar_one())
    return tile
