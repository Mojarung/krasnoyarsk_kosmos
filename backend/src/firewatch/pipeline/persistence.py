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
# Соседей ищем по индексу ячейки сетки VIIRS 375 м: соединение по равенству вместо перебора всех пар.
# Координаты центров хранятся округлёнными, но округление на полметра границу ячейки не пересекает.
GRID_STEP_M = 375.0

_REFRESH_SOURCES = text(
    """
    WITH det AS (
        SELECT epsg, x_utm, y_utm, acquired_at, geom,
               floor(x_utm / :step)::int AS gx, floor(y_utm / :step)::int AS gy
        FROM hotspots WHERE code IN (1, 2)
    ), cell AS (
        SELECT DISTINCT ON (epsg, gx, gy) epsg, gx, gy, x_utm, y_utm, geom FROM det
    ), offsets AS (
        SELECT dx, dy FROM (VALUES (-1), (0), (1)) a(dx) CROSS JOIN (VALUES (-1), (0), (1)) b(dy)
    ), agg AS (
        SELECT c.epsg, c.x_utm, c.y_utm, c.geom,
               count(*) AS n_detections,
               count(DISTINCT d.acquired_at::date) AS n_days,
               count(DISTINCT date_part('year', d.acquired_at)) AS n_years,
               min(d.acquired_at) AS first_seen,
               max(d.acquired_at) AS last_seen
        FROM cell c
        CROSS JOIN offsets o
        JOIN det d ON d.epsg = c.epsg AND d.gx = c.gx + o.dx AND d.gy = c.gy + o.dy
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
    WITH offsets AS (
        SELECT dx, dy FROM (VALUES (-1), (0), (1)) a(dx) CROSS JOIN (VALUES (-1), (0), (1)) b(dy)
    ), near_source AS (
        SELECT DISTINCT p.epsg, floor(p.x_utm / :step)::int + o.dx AS gx, floor(p.y_utm / :step)::int + o.dy AS gy
        FROM persistent_sources p CROSS JOIN offsets o
    ), flagged AS (
        SELECT h2.id, (n.epsg IS NOT NULL) AS value
        FROM hotspots h2
        LEFT JOIN near_source n ON n.epsg = h2.epsg
             AND n.gx = floor(h2.x_utm / :step)::int AND n.gy = floor(h2.y_utm / :step)::int
    )
    UPDATE hotspots h SET persistent = flagged.value
    FROM flagged
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
            "step": GRID_STEP_M,
            "min_days": s.persistent_min_days,
            "min_years": s.persistent_min_years,
            "min_share": s.persistent_min_pass_share,
        },
    )
    await session.execute(_FLAG_HOTSPOTS, {"step": GRID_STEP_M})
    return True
