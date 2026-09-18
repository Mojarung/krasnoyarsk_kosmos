from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from firewatch.domain.catalog import LC_GROUP_LABELS, lc_group
from firewatch.services.query import CLIPPED_HA, QUERY_GEOM, SpatioTemporalQuery

SCORE_WEIGHTS = {"f1_af": 0.35, "iou_burn": 0.35, "miou_sev": 0.30}
KELVIN_OFFSET = 273.15
TOP_CONTOURS = 5

_NATURAL = "h.code = 1 AND NOT h.persistent"
_IN_QUERY = (
    "ST_Intersects(h.geom, q.geom) AND h.acquired_at >= :date_from AND h.acquired_at < :date_to_exclusive"
)

_QUALITY = text(
    f"""
    WITH q AS (SELECT {QUERY_GEOM} AS geom)
    SELECT sc.kind, sc.stats -> 'quality' AS quality
    FROM scenes sc CROSS JOIN q
    WHERE sc.status = 'ready' AND sc.stats ? 'quality' AND ST_Intersects(sc.footprint, q.geom)
      AND ((sc.kind = 'af' AND sc.acquired_at >= :date_from AND sc.acquired_at < :date_to_exclusive)
        OR (sc.kind = 'bs' AND sc.date_pre <= :date_to AND sc.date_post >= :date_from))
    """
)

_HOTSPOT_STATS = text(
    f"""
    WITH q AS (SELECT {QUERY_GEOM} AS geom)
    SELECT count(*) AS n, avg(h.bt_i4) AS bt_i4_mean, max(h.bt_i4) AS bt_i4_max,
           avg(h.bt_i4 - h.bt_i5) AS delta_mean, avg(h.confidence) AS confidence_mean,
           count(*) FILTER (WHERE h.is_night) AS night, avg(h.t2m) AS t2m_mean, avg(h.rh2m) AS rh2m_mean,
           avg(h.wind_speed) AS wind_mean, max(h.wind_speed) AS wind_max,
           count(DISTINCT h.acquired_at::date) AS active_days, count(DISTINCT h.scene_id) AS passes
    FROM hotspots h CROSS JOIN q WHERE {_IN_QUERY} AND {_NATURAL}
    """
)

_HOTSPOT_LANDCOVER = text(
    f"""
    WITH q AS (SELECT {QUERY_GEOM} AS geom)
    SELECT h.landcover, count(*) AS n FROM hotspots h CROSS JOIN q
    WHERE {_IN_QUERY} AND {_NATURAL} GROUP BY 1
    """
)

_HOTSPOT_MONTHS = text(
    f"""
    WITH q AS (SELECT {QUERY_GEOM} AS geom)
    SELECT to_char(h.acquired_at, 'YYYY-MM') AS month, count(*) AS n FROM hotspots h CROSS JOIN q
    WHERE {_IN_QUERY} AND {_NATURAL} GROUP BY 1 ORDER BY 1
    """
)

_BURN_STATS = text(
    f"""
    WITH q AS (SELECT {QUERY_GEOM} AS geom), hit AS (
        SELECT b.id, b.scene_id, b.date_post, {CLIPPED_HA.format(t="b")} AS ha
        FROM burn_areas b CROSS JOIN q
        WHERE ST_Intersects(b.geom, q.geom) AND b.date_pre <= :date_to AND b.date_post >= :date_from
    )
    SELECT count(*) AS contours, coalesce(avg(ha), 0) AS mean_ha, coalesce(max(ha), 0) AS max_ha,
           coalesce(percentile_cont(0.5) WITHIN GROUP (ORDER BY ha), 0) AS median_ha,
           (SELECT ST_Area(geom::geography) / 10000.0 FROM q) AS query_ha
    FROM hit
    """
)

_BURN_MONTHS = text(
    f"""
    WITH q AS (SELECT {QUERY_GEOM} AS geom)
    SELECT to_char(b.date_post, 'YYYY-MM') AS month, sum({CLIPPED_HA.format(t="b")}) AS ha, count(*) AS contours
    FROM burn_areas b CROSS JOIN q
    WHERE ST_Intersects(b.geom, q.geom) AND b.date_pre <= :date_to AND b.date_post >= :date_from
    GROUP BY 1 ORDER BY 1
    """
)

_BURN_TOP = text(
    f"""
    WITH q AS (SELECT {QUERY_GEOM} AS geom)
    SELECT b.id, b.scene_id, b.date_post, {CLIPPED_HA.format(t="b")} AS ha,
           ST_X(ST_PointOnSurface(b.geom)) AS lon, ST_Y(ST_PointOnSurface(b.geom)) AS lat
    FROM burn_areas b CROSS JOIN q
    WHERE ST_Intersects(b.geom, q.geom) AND b.date_pre <= :date_to AND b.date_post >= :date_from
    ORDER BY ha DESC LIMIT :top
    """
)

_PIPELINE = text(
    """
    SELECT kind, count(*) AS scenes, avg((stats ->> 'duration_ms')::float) AS mean_ms,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY (stats ->> 'duration_ms')::float) AS p95_ms
    FROM scenes WHERE status = 'ready' AND stats ? 'duration_ms' GROUP BY kind
    """
)

_THROUGHPUT = text(
    "SELECT count(*) FROM scenes WHERE status = 'ready' AND processed_at > now() - interval '1 minute'"
)


def _f1(c: dict[str, int]) -> float:
    denominator = 2 * c["tp"] + c["fp"] + c["fn"]
    return 2 * c["tp"] / denominator if denominator else 1.0


def _iou(c: dict[str, int]) -> float:
    denominator = c["tp"] + c["fp"] + c["fn"]
    return c["tp"] / denominator if denominator else 1.0


def _add(total: dict[str, int], part: dict[str, int]) -> None:
    for key in ("tp", "fp", "fn"):
        total[key] += part[key]


def score_from_scenes(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Метрика соревнования с микро-усреднением: TP, FP, FN суммируются по сценам, потом берутся доли."""
    fire: dict[str, int] = defaultdict(int)
    burn: dict[str, int] = defaultdict(int)
    severity: list[dict[str, int]] = [defaultdict(int) for _ in range(3)]
    af_scenes = bs_scenes = 0
    for row in rows:
        quality = row["quality"]
        if row["kind"] == "af":
            af_scenes += 1
            _add(fire, quality["fire"])
        else:
            bs_scenes += 1
            _add(burn, quality["burn"])
            for total, part in zip(severity, quality["severity"], strict=True):
                _add(total, part)
    if not af_scenes and not bs_scenes:
        return None

    f1_af = _f1(fire) if af_scenes else None
    iou_burn = _iou(burn) if bs_scenes else None
    iou_sev = [_iou(c) for c in severity] if bs_scenes else None
    miou_sev = sum(iou_sev) / 3 if iou_sev else None
    parts = {"f1_af": f1_af, "iou_burn": iou_burn, "miou_sev": miou_sev}
    complete = all(v is not None for v in parts.values())
    precision = fire["tp"] / (fire["tp"] + fire["fp"]) if fire["tp"] + fire["fp"] else None
    recall = fire["tp"] / (fire["tp"] + fire["fn"]) if fire["tp"] + fire["fn"] else None
    return {
        "af_scenes": af_scenes,
        "bs_scenes": bs_scenes,
        "f1_af": _r4(f1_af),
        "precision_af": _r4(precision),
        "recall_af": _r4(recall),
        "iou_burn": _r4(iou_burn),
        "iou_severity": [_r4(v) for v in iou_sev] if iou_sev else None,
        "miou_sev": _r4(miou_sev),
        "score": _r4(sum(SCORE_WEIGHTS[k] * v for k, v in parts.items())) if complete else None,
        "note": "Считается по сценам запроса, для которых загружена эталонная маска. Формула и усреднение как в постановке кейса.",
    }


def _r4(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def _r1(value: float | None) -> float | None:
    return None if value is None else round(float(value), 1)


def _celsius(value: float | None) -> float | None:
    if value is None:
        return None
    return _r1(value - KELVIN_OFFSET if value > 200 else value)


async def fetch_quality(session: AsyncSession, query: SpatioTemporalQuery) -> dict[str, Any] | None:
    rows = [dict(r) for r in (await session.execute(_QUALITY, query.sql_params)).mappings()]
    return score_from_scenes(rows)


async def fetch_hotspot_metrics(session: AsyncSession, query: SpatioTemporalQuery) -> dict[str, Any]:
    params = query.sql_params
    stats = (await session.execute(_HOTSPOT_STATS, params)).mappings().one()
    by_group: dict[str, int] = defaultdict(int)
    for row in (await session.execute(_HOTSPOT_LANDCOVER, params)).mappings():
        by_group[lc_group(row["landcover"])] += row["n"]
    months = [dict(r) for r in (await session.execute(_HOTSPOT_MONTHS, params)).mappings()]
    n = stats["n"]
    return {
        "bt_i4_mean_k": _r1(stats["bt_i4_mean"]),
        "bt_i4_max_k": _r1(stats["bt_i4_max"]),
        "delta_mean_k": _r1(stats["delta_mean"]),
        "confidence_mean": _r4(stats["confidence_mean"]),
        "night_share": _r4(stats["night"] / n) if n else None,
        "active_days": stats["active_days"],
        "passes_with_fire": stats["passes"],
        "weather": {
            "t2m_mean_c": _celsius(stats["t2m_mean"]),
            "rh2m_mean": _r1(stats["rh2m_mean"]),
            "wind_mean_ms": _r1(stats["wind_mean"]),
            "wind_max_ms": _r1(stats["wind_max"]),
        },
        "by_landcover": [
            {"landcover": g, "label": LC_GROUP_LABELS[g], "n": count, "share": _r4(count / n)}
            for g, count in sorted(by_group.items(), key=lambda kv: -kv[1])
        ],
        "by_month": months,
        "peak_month": max(months, key=lambda m: m["n"])["month"] if months else None,
    }


async def fetch_burn_metrics(
    session: AsyncSession, query: SpatioTemporalQuery, total_ha: float, severity_ha: list[float]
) -> dict[str, Any]:
    params = query.sql_params
    stats = (await session.execute(_BURN_STATS, params)).mappings().one()
    months = (await session.execute(_BURN_MONTHS, params)).mappings()
    top = (await session.execute(_BURN_TOP, params | {"top": TOP_CONTOURS})).mappings()
    weighted = sum((k + 1) * ha for k, ha in enumerate(severity_ha))
    return {
        "contours": stats["contours"],
        "mean_ha": round(stats["mean_ha"], 2),
        "median_ha": round(stats["median_ha"], 2),
        "max_ha": round(stats["max_ha"], 2),
        "query_area_km2": round(stats["query_ha"] / 100.0, 1),
        "burned_share": _r4(total_ha / stats["query_ha"]) if stats["query_ha"] else None,
        "severity_index": round(weighted / total_ha, 3) if total_ha else None,
        "by_month": [
            {"month": m["month"], "area_ha": round(m["ha"], 2), "contours": m["contours"]} for m in months
        ],
        "largest": [
            {
                "contour_id": t["id"],
                "scene_id": t["scene_id"],
                "date_post": t["date_post"].isoformat(),
                "area_ha": round(t["ha"], 2),
                "lon": round(t["lon"], 5),
                "lat": round(t["lat"], 5),
            }
            for t in top
        ],
    }


async def fetch_pipeline_metrics(session: AsyncSession) -> dict[str, Any]:
    rows = (await session.execute(_PIPELINE)).mappings()
    per_minute = (await session.execute(_THROUGHPUT)).scalar_one()
    return {
        "scenes_last_minute": per_minute,
        "by_kind": {
            r["kind"]: {"scenes": r["scenes"], "mean_ms": round(r["mean_ms"]), "p95_ms": round(r["p95_ms"])}
            for r in rows
        },
    }
