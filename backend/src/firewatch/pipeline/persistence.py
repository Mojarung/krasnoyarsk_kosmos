"""Постоянные источники тепла.

Факел или печь по одному снимку неотличимы от пожара. Их выдаёт история: ячейка
горит почти в каждом пролёте и из года в год. Правило считается по накопленным
детекциям в БД, поэтому уточняется с каждой новой сценой.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from firewatch.config import get_settings
from firewatch.infra.cache import redis

_LOCK_ID = 74001
DIRTY_KEY = "fw:persistence_dirty"

_REFRESH_SOURCES = text(
    """
    WITH det AS (
        SELECT epsg, x_utm, y_utm, acquired_at, geom FROM hotspots WHERE code IN (1, 2)
    ), cell AS (
        SELECT DISTINCT ON (epsg, x_utm, y_utm) epsg, x_utm, y_utm, geom FROM det
    ), agg AS (
        SELECT c.epsg, c.x_utm, c.y_utm, c.geom,
               count(*) AS n_detections,
               count(DISTINCT d.acquired_at::date) AS n_days,
               count(DISTINCT date_part('year', d.acquired_at)) AS n_years,
               min(d.acquired_at) AS first_seen,
               max(d.acquired_at) AS last_seen
        FROM cell c
        JOIN det d ON d.epsg = c.epsg
                  AND d.x_utm BETWEEN c.x_utm - :radius AND c.x_utm + :radius
                  AND d.y_utm BETWEEN c.y_utm - :radius AND c.y_utm + :radius
        GROUP BY c.epsg, c.x_utm, c.y_utm, c.geom
        HAVING count(DISTINCT d.acquired_at::date) >= :min_days
           AND count(DISTINCT date_part('year', d.acquired_at)) >= :min_years
    ), scored AS (
        SELECT a.*, (
            SELECT count(DISTINCT s.acquired_at::date) FROM scenes s
            WHERE s.kind = 'af' AND s.status = 'ready' AND ST_Intersects(s.footprint, a.geom)
        ) AS n_passes
        FROM agg a
    )
    INSERT INTO persistent_sources
        (epsg, x_utm, y_utm, geom, n_detections, n_days, n_years, n_passes, first_seen, last_seen)
    SELECT epsg, x_utm, y_utm, geom, n_detections, n_days, n_years, n_passes, first_seen, last_seen
    FROM scored
    WHERE n_passes > 0 AND n_days::float / n_passes >= :min_share
    """
)

_FLAG_HOTSPOTS = text(
    """
    UPDATE hotspots h SET persistent = flagged.value
    FROM (
        SELECT h2.id, EXISTS (
            SELECT 1 FROM persistent_sources p
            WHERE p.epsg = h2.epsg
              AND h2.x_utm BETWEEN p.x_utm - :radius AND p.x_utm + :radius
              AND h2.y_utm BETWEEN p.y_utm - :radius AND p.y_utm + :radius
        ) AS value
        FROM hotspots h2
    ) flagged
    WHERE flagged.id = h.id AND h.persistent IS DISTINCT FROM flagged.value
    """
)


async def mark_dirty() -> None:
    await redis.set(DIRTY_KEY, "1")


async def refresh_persistent_sources(session: AsyncSession) -> bool:
    """Пересчитывает источники, если после последнего пересчёта появились новые детекции.

    Воркеры выстраиваются на advisory lock. Тот, кто получил его первым, забирает флаг и считает,
    остальные видят, что флага уже нет, и выходят: их данные закоммичены до чужого пересчёта.
    """
    s = get_settings()
    await session.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": _LOCK_ID})
    if await redis.getdel(DIRTY_KEY) is None:
        return False
    await session.execute(text("DELETE FROM persistent_sources"))
    await session.execute(
        _REFRESH_SOURCES,
        {
            "radius": s.persistent_radius_m,
            "min_days": s.persistent_min_days,
            "min_years": s.persistent_min_years,
            "min_share": s.persistent_min_pass_share,
        },
    )
    await session.execute(_FLAG_HOTSPOTS, {"radius": s.persistent_radius_m})
    return True
