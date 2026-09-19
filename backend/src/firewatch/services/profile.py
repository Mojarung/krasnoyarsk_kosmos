"""Профиль территории за всю историю наблюдений.

Справка отвечает на вопрос «что горело в этот период». Профиль отвечает на другой:
типичен ли этот период для территории. Поэтому здесь период запроса не фильтрует данные,
а только подсвечивается: агрегаты считаются по всем годам, какие есть в базе.

Устроено как «Country Profile» в GWIS: межгодовой ход, сезонность, повторяемость горимости
и отклонение года от среднего.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from firewatch.services.query import CLIPPED_HA, QUERY_GEOM, SpatioTemporalQuery

GRID_STEP_M = 375.0
"""Шаг сетки VIIRS: повторяемость считается по ячейкам этой сетки."""

CELL_AREA_HA = GRID_STEP_M * GRID_STEP_M / 10_000.0

MONTH_NAMES = [
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
]

METHOD = (
    "Годы и сезонность считаются по всем данным в базе, период запроса только подсвечен. "
    "Повторяемость - по ячейкам сетки VIIRS 375 м: в скольких разных годах ячейка попадала "
    "в природную термоточку. Отклонение года - разница с средним по остальным годам."
)

_NATURAL = "h.code = 1 AND NOT h.persistent"

_YEARS = text(
    f"""
    WITH q AS (SELECT {QUERY_GEOM} AS geom), fires AS (
        SELECT date_part('year', h.acquired_at)::int AS year, count(*) AS hotspots,
               count(DISTINCT h.acquired_at::date) AS active_days, sum(h.frp_mw) AS frp_mw
        FROM hotspots h CROSS JOIN q
        WHERE ST_Intersects(h.geom, q.geom) AND {_NATURAL}
        GROUP BY 1
    ), burns AS (
        SELECT date_part('year', b.date_post)::int AS year, count(*) AS contours,
               sum({CLIPPED_HA.format(t="b")}) AS area_ha
        FROM burn_areas b CROSS JOIN q WHERE ST_Intersects(b.geom, q.geom)
        GROUP BY 1
    )
    SELECT coalesce(f.year, b.year) AS year,
           coalesce(f.hotspots, 0) AS hotspots, coalesce(f.active_days, 0) AS active_days,
           f.frp_mw, coalesce(b.contours, 0) AS contours, coalesce(b.area_ha, 0) AS area_ha
    FROM fires f FULL OUTER JOIN burns b ON b.year = f.year
    ORDER BY 1
    """
)

_SEASON = text(
    f"""
    WITH q AS (SELECT {QUERY_GEOM} AS geom), fires AS (
        SELECT date_part('month', h.acquired_at)::int AS month, count(*) AS hotspots,
               count(DISTINCT date_part('year', h.acquired_at)) AS years
        FROM hotspots h CROSS JOIN q
        WHERE ST_Intersects(h.geom, q.geom) AND {_NATURAL}
        GROUP BY 1
    ), burns AS (
        SELECT date_part('month', b.date_post)::int AS month, sum({CLIPPED_HA.format(t="b")}) AS area_ha
        FROM burn_areas b CROSS JOIN q WHERE ST_Intersects(b.geom, q.geom)
        GROUP BY 1
    )
    SELECT coalesce(f.month, b.month) AS month, coalesce(f.hotspots, 0) AS hotspots,
           coalesce(f.years, 0) AS years, coalesce(b.area_ha, 0) AS area_ha
    FROM fires f FULL OUTER JOIN burns b ON b.month = f.month
    ORDER BY 1
    """
)

_RECURRENCE = text(
    f"""
    WITH q AS (SELECT {QUERY_GEOM} AS geom), cells AS (
        SELECT h.epsg, floor(h.x_utm / :step)::int AS gx, floor(h.y_utm / :step)::int AS gy,
               count(DISTINCT date_part('year', h.acquired_at)) AS years
        FROM hotspots h CROSS JOIN q
        WHERE ST_Intersects(h.geom, q.geom) AND {_NATURAL}
        GROUP BY 1, 2, 3
    )
    SELECT years, count(*) AS cells FROM cells GROUP BY 1 ORDER BY 1
    """
)

_COVERAGE = text(
    f"""
    WITH q AS (SELECT {QUERY_GEOM} AS geom)
    SELECT min(sc.acquired_at)::date AS first_day, max(sc.acquired_at)::date AS last_day,
           count(*) FILTER (WHERE sc.kind = 'af') AS af_scenes,
           count(*) FILTER (WHERE sc.kind = 'bs') AS bs_scenes
    FROM scenes sc CROSS JOIN q
    WHERE sc.status = 'ready' AND ST_Intersects(sc.footprint, q.geom)
    """
)

_AREA = text(f"SELECT ST_Area(({QUERY_GEOM})::geography) / 10000.0")


def _deviation(value: float, others: list[float]) -> float | None:
    """Отклонение года от среднего по остальным годам, в долях. Без остальных лет смысла нет."""
    if not others:
        return None
    baseline = sum(others) / len(others)
    return round((value - baseline) / baseline, 3) if baseline else None


def _years_block(rows: list[dict[str, Any]], highlight: set[int]) -> list[dict[str, Any]]:
    areas = {r["year"]: float(r["area_ha"]) for r in rows}
    counts = {r["year"]: r["hotspots"] for r in rows}
    return [
        {
            "year": r["year"],
            "hotspots": r["hotspots"],
            "active_days": r["active_days"],
            "frp_mw": round(r["frp_mw"], 1) if r["frp_mw"] is not None else None,
            "contours": r["contours"],
            "area_ha": round(float(r["area_ha"]), 2),
            "area_deviation": _deviation(
                float(r["area_ha"]), [v for y, v in areas.items() if y != r["year"]]
            ),
            "hotspot_deviation": _deviation(
                r["hotspots"], [float(v) for y, v in counts.items() if y != r["year"]]
            ),
            "in_query": r["year"] in highlight,
        }
        for r in rows
    ]


def _season_block(rows: list[dict[str, Any]], n_years: int) -> list[dict[str, Any]]:
    by_month = {r["month"]: r for r in rows}
    return [
        {
            "month": month,
            "label": MONTH_NAMES[month - 1],
            "hotspots": int(by_month[month]["hotspots"]) if month in by_month else 0,
            "hotspots_per_year": round(by_month[month]["hotspots"] / n_years, 1)
            if month in by_month and n_years
            else 0.0,
            "area_ha": round(float(by_month[month]["area_ha"]), 2) if month in by_month else 0.0,
            "years_seen": int(by_month[month]["years"]) if month in by_month else 0,
        }
        for month in range(1, 13)
    ]


def _recurrence_block(rows: list[dict[str, Any]], query_ha: float) -> dict[str, Any]:
    buckets = [{"years": int(r["years"]), "cells": r["cells"]} for r in rows]
    total_cells = sum(b["cells"] for b in buckets)
    repeat_cells = sum(b["cells"] for b in buckets if b["years"] >= 2)
    return {
        "cell_area_ha": CELL_AREA_HA,
        "touched_cells": total_cells,
        "touched_ha": round(total_cells * CELL_AREA_HA, 2),
        "touched_share": round(total_cells * CELL_AREA_HA / query_ha, 4) if query_ha else None,
        "repeat_cells": repeat_cells,
        "repeat_ha": round(repeat_cells * CELL_AREA_HA, 2),
        "repeat_share": round(repeat_cells / total_cells, 4) if total_cells else None,
        "max_years": max((b["years"] for b in buckets), default=0),
        "buckets": [
            {
                "years": b["years"],
                "cells": b["cells"],
                "area_ha": round(b["cells"] * CELL_AREA_HA, 2),
                "share": round(b["cells"] / total_cells, 4) if total_cells else 0.0,
            }
            for b in buckets
        ],
    }


async def build_profile(session: AsyncSession, query: SpatioTemporalQuery) -> dict[str, Any]:
    params = {"geometry": query.sql_params["geometry"]}
    years_rows = [dict(r) for r in (await session.execute(_YEARS, params)).mappings()]
    season_rows = [dict(r) for r in (await session.execute(_SEASON, params)).mappings()]
    recurrence_rows = [
        dict(r) for r in (await session.execute(_RECURRENCE, params | {"step": GRID_STEP_M})).mappings()
    ]
    coverage = (await session.execute(_COVERAGE, params)).mappings().one()
    query_ha = float((await session.execute(_AREA, params)).scalar_one())

    highlight = set(range(query.date_from.year, query.date_to.year + 1))
    years = _years_block(years_rows, highlight)
    season = _season_block(season_rows, len({y["year"] for y in years}))
    peak = max(season, key=lambda m: m["hotspots"]) if any(m["hotspots"] for m in season) else None
    worst = max(years, key=lambda y: y["area_ha"]) if years else None

    return {
        "query": {
            "geometry": query.geometry,
            "date_from": query.date_from.isoformat(),
            "date_to": query.date_to.isoformat(),
            "area_km2": round(query_ha / 100.0, 1),
        },
        "coverage": {
            "first_day": _iso(coverage["first_day"]),
            "last_day": _iso(coverage["last_day"]),
            "af_scenes": coverage["af_scenes"],
            "bs_scenes": coverage["bs_scenes"],
            "years": len(years),
        },
        "years": years,
        "season": season,
        "peak_month": peak["label"] if peak else None,
        "fire_season": _fire_season(season),
        "worst_year": worst["year"] if worst and worst["area_ha"] > 0 else None,
        "recurrence": _recurrence_block(recurrence_rows, query_ha),
        "method": METHOD,
    }


def _fire_season(season: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Ядро пожарного сезона: подряд идущие месяцы, которые вместе дают 80% термоточек."""
    total = sum(m["hotspots"] for m in season)
    if not total:
        return None
    best: tuple[int, int, int] | None = None
    for start in range(12):
        collected = 0
        for length in range(1, 13):
            collected += season[(start + length - 1) % 12]["hotspots"]
            if collected >= 0.8 * total:
                if best is None or length < best[2]:
                    best = (start, collected, length)
                break
    if best is None:
        return None
    start, collected, length = best
    months = [season[(start + i) % 12]["label"] for i in range(length)]
    return {
        "from": months[0],
        "to": months[-1],
        "months": length,
        "share": round(collected / total, 4),
    }


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None
