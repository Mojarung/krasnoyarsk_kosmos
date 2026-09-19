from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from shapely.geometry import box, mapping, shape
from shapely.geometry.base import BaseGeometry
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from firewatch.config import get_settings
from firewatch.domain.catalog import HOTSPOT_KIND_LABELS, LC_GROUP_LABELS, SEVERITY_LABELS, lc_group
from firewatch.pipeline.frp import I4_SATURATION_K

CLUSTER_EPSG = 32638
QUERY_GEOM = "ST_SetSRID(ST_GeomFromGeoJSON(:geometry), 4326)"
# В регионе сотни тысяч полигонов степеней, геометрическая проверка каждого стоит секунды.
# Если след сцены целиком внутри запроса, все её контуры тоже внутри: их площади складываются
# без геометрии. По-честному режутся только сцены, которые запрос пересекает по границе.
# Геометрия запроса подставляется в предикаты выражением, а не через JOIN с CTE: так PostGIS
# кеширует подготовленную геометрию между строками. Через материализованный CTE тот же запрос
# выполнялся 12-21 с вместо 0,7 с.
SCENES_IN_QUERY = f"""
    hit AS MATERIALIZED (
        SELECT sc.id, ST_Within(sc.footprint, {QUERY_GEOM}) AS whole
        FROM scenes sc
        WHERE sc.kind = 'bs' AND sc.status = 'ready' AND ST_Intersects(sc.footprint, {QUERY_GEOM})
          AND sc.date_pre <= :date_to AND sc.date_post >= :date_from
    )"""
CLIPPED_HA_INLINE = (
    "CASE WHEN ST_Within({t}.geom, " + QUERY_GEOM + ") THEN {t}.area_ha "
    "ELSE ST_Area(ST_Transform(ST_Intersection({t}.geom, " + QUERY_GEOM + "), {t}.epsg)) / 10000.0 END"
)
_KIND_SQL = (
    "CASE WHEN h.code = 3 THEN 'glint' WHEN h.code = 2 OR h.persistent THEN 'technogenic' ELSE 'fire' END"
)
CLIPPED_HA = """CASE WHEN ST_Within({t}.geom, q.geom) THEN {t}.area_ha
    ELSE ST_Area(ST_Transform(ST_Intersection({t}.geom, q.geom), {t}.epsg)) / 10000.0 END"""


class InvalidQueryError(ValueError):
    pass


@dataclass(frozen=True)
class SpatioTemporalQuery:
    geometry: dict[str, Any]
    date_from: date
    date_to: date

    @classmethod
    def build(
        cls,
        *,
        geometry: dict[str, Any] | None,
        bbox: tuple[float, float, float, float] | None,
        date_from: date,
        date_to: date,
    ) -> SpatioTemporalQuery:
        if date_from > date_to:
            raise InvalidQueryError("date_from позже date_to")
        if geometry is None and bbox is None:
            raise InvalidQueryError("Нужен полигон (geometry) или ограничивающий прямоугольник (bbox)")
        geom = parse_geometry(geometry) if geometry is not None else _parse_bbox(bbox)
        return cls(geometry=mapping(geom), date_from=date_from, date_to=date_to)

    @property
    def sql_params(self) -> dict[str, Any]:
        return {
            "geometry": json.dumps(self.geometry),
            "date_from": self.date_from,
            "date_to": self.date_to,
            "date_to_exclusive": self.date_to + timedelta(days=1),
        }

    @property
    def cache_key(self) -> dict[str, Any]:
        return {"g": self.geometry, "f": self.date_from.isoformat(), "t": self.date_to.isoformat()}


def parse_geometry(geometry: dict[str, Any]) -> BaseGeometry:
    try:
        geom = shape(geometry)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise InvalidQueryError(f"Некорректный GeoJSON: {exc}") from exc
    if geom.geom_type not in ("Polygon", "MultiPolygon"):
        raise InvalidQueryError("Ожидается Polygon или MultiPolygon")
    if not geom.is_valid:
        geom = geom.buffer(0)
    if geom.is_empty:
        raise InvalidQueryError("Пустая геометрия")
    _check_lonlat(geom.bounds)
    return geom


def _parse_bbox(bbox: tuple[float, float, float, float]) -> BaseGeometry:
    west, south, east, north = bbox
    if west >= east or south >= north:
        raise InvalidQueryError("bbox задаётся как west,south,east,north")
    _check_lonlat(bbox)
    return box(west, south, east, north)


def _check_lonlat(bounds: tuple[float, float, float, float]) -> None:
    west, south, east, north = bounds
    if west < -180 or east > 180 or south < -90 or north > 90:
        raise InvalidQueryError("Координаты должны быть в WGS 84 (долгота, широта)")


_HOTSPOTS = text(
    f"""
    WITH q AS (SELECT {QUERY_GEOM} AS geom)
    SELECT h.id, ST_X(h.geom) AS lon, ST_Y(h.geom) AS lat, h.acquired_at, h.satellite, h.scene_id,
           {_KIND_SQL} AS kind, h.code, h.persistent, h.bt_i4, h.bt_i5, h.frp_mw, h.confidence, h.landcover,
           h.is_night, h.t2m, h.rh2m, h.wind_speed, p.n_days, p.n_years, p.n_passes
    FROM hotspots h
    CROSS JOIN q
    LEFT JOIN LATERAL (
        SELECT ps.n_days, ps.n_years, ps.n_passes FROM persistent_sources ps
        WHERE h.persistent AND ps.epsg = h.epsg
          AND h.x_utm BETWEEN ps.x_utm - :radius AND ps.x_utm + :radius
          AND h.y_utm BETWEEN ps.y_utm - :radius AND ps.y_utm + :radius
        ORDER BY ps.n_days DESC LIMIT 1
    ) p ON TRUE
    WHERE ST_Intersects(h.geom, q.geom)
      AND h.acquired_at >= :date_from AND h.acquired_at < :date_to_exclusive
    ORDER BY h.acquired_at
    """
)

_HOTSPOT_SUMMARY = text(
    f"""
    WITH q AS (SELECT {QUERY_GEOM} AS geom), pts AS (
        SELECT {_KIND_SQL} AS kind, h.acquired_at::date AS day,
               ST_ClusterDBSCAN(ST_Transform(h.geom, {CLUSTER_EPSG}), eps := :eps, minpoints := 1)
                   OVER (PARTITION BY {_KIND_SQL}, h.acquired_at::date) AS cluster_id
        FROM hotspots h CROSS JOIN q
        WHERE ST_Intersects(h.geom, q.geom)
          AND h.acquired_at >= :date_from AND h.acquired_at < :date_to_exclusive
    )
    SELECT kind, day, count(*) AS n, count(DISTINCT cluster_id) AS clusters
    FROM pts GROUP BY kind, day ORDER BY day
    """
)

_SATELLITES = text(
    f"""
    WITH q AS (SELECT {QUERY_GEOM} AS geom)
    SELECT coalesce(h.satellite, 'неизвестно') AS satellite, count(*) AS n
    FROM hotspots h CROSS JOIN q
    WHERE ST_Intersects(h.geom, q.geom) AND h.code = 1 AND NOT h.persistent
      AND h.acquired_at >= :date_from AND h.acquired_at < :date_to_exclusive
    GROUP BY 1 ORDER BY 2 DESC
    """
)

_BURN_AREAS = text(
    f"""
    WITH q AS (SELECT {QUERY_GEOM} AS geom)
    SELECT b.id, b.scene_id, b.fire_event_id, b.epsg, b.date_pre, b.date_post,
           b.area_ha AS full_area_ha, b.sev1_ha, b.sev2_ha, b.sev3_ha,
           ST_Within(b.geom, q.geom) AS is_whole,
           {CLIPPED_HA.format(t="b")} AS area_ha,
           ST_AsGeoJSON(CASE WHEN ST_Within(b.geom, q.geom) THEN b.geom
                        ELSE ST_Multi(ST_CollectionExtract(ST_Intersection(b.geom, q.geom), 3)) END, 7) AS geojson
    FROM burn_areas b CROSS JOIN q
    WHERE ST_Intersects(b.geom, q.geom) AND b.date_pre <= :date_to AND b.date_post >= :date_from
    ORDER BY b.area_ha DESC
    """
)

_SEVERITY_POLYGONS = text(
    f"""
    WITH q AS (SELECT {QUERY_GEOM} AS geom)
    SELECT s.id, s.burn_area_id, s.scene_id, s.severity, s.epsg, s.date_post, sc.date_pre, sc.fire_event_id,
           {CLIPPED_HA.format(t="s")} AS area_ha,
           ST_AsGeoJSON(CASE WHEN ST_Within(s.geom, q.geom) THEN s.geom
                        ELSE ST_CollectionExtract(ST_Intersection(s.geom, q.geom), 3) END, 7) AS geojson
    FROM severity_polygons s JOIN scenes sc ON sc.id = s.scene_id CROSS JOIN q
    WHERE ST_Intersects(s.geom, q.geom) AND sc.date_pre <= :date_to AND sc.date_post >= :date_from
    """
)

_SEVERITY_BY_SCENE = text(
    f"""
    WITH {SCENES_IN_QUERY}
    SELECT s.scene_id, s.severity, sum(s.area_ha) AS area_ha
    FROM hit JOIN severity_polygons s ON s.scene_id = hit.id
    WHERE hit.whole
    GROUP BY s.scene_id, s.severity
    UNION ALL
    SELECT s.scene_id, s.severity, sum({CLIPPED_HA_INLINE.format(t="s")}) AS area_ha
    FROM hit JOIN severity_polygons s ON s.scene_id = hit.id
    WHERE NOT hit.whole AND ST_Intersects(s.geom, {QUERY_GEOM})
    GROUP BY s.scene_id, s.severity
    """
)

_LANDCOVER = text(
    "SELECT scene_id, severity, lc_group, area_ha FROM scar_landcover WHERE scene_id = ANY(:scene_ids)"
)

_SCENE_TOTALS = text(
    "SELECT scene_id, severity, sum(area_ha) AS area_ha FROM severity_polygons WHERE scene_id = ANY(:scene_ids) GROUP BY 1, 2"
)


def _reason(row: dict[str, Any]) -> str | None:
    if row["kind"] == "glint":
        return "Солнечный блик: вода или сильное отражение в SWIR при дневной съёмке"
    if row["kind"] != "technogenic":
        return None
    if row["persistent"] and row["n_days"]:
        return f"Постоянный источник: горит в {row['n_days']} из {row['n_passes']} пролётов за {row['n_years']} г."
    return "Термоаномалия на застройке или промплощадке (ESA WorldCover)"


def _hotspot_feature(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "Feature",
        "id": row["id"],
        "geometry": {"type": "Point", "coordinates": [round(row["lon"], 6), round(row["lat"], 6)]},
        "properties": {
            "id": row["id"],
            "kind": row["kind"],
            "kind_label": HOTSPOT_KIND_LABELS[row["kind"]],
            "reason": _reason(row),
            "acquired_at": row["acquired_at"].isoformat(),
            "ts": int(row["acquired_at"].timestamp()),
            "satellite": row["satellite"],
            "scene_id": row["scene_id"],
            "bt_i4": round(row["bt_i4"], 1),
            "bt_i5": round(row["bt_i5"], 1),
            "frp_mw": _rounded(row["frp_mw"]),
            "frp_saturated": row["bt_i4"] >= I4_SATURATION_K,
            "confidence": round(row["confidence"], 2),
            "landcover": LC_GROUP_LABELS[lc_group(row["landcover"])],
            "is_night": row["is_night"],
            "t2m": _rounded(row["t2m"]),
            "rh2m": _rounded(row["rh2m"]),
            "wind_speed": _rounded(row["wind_speed"]),
        },
    }


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


async def fetch_hotspots(
    session: AsyncSession, query: SpatioTemporalQuery, kinds: set[str] | None = None
) -> dict[str, Any]:
    params = query.sql_params | {"radius": get_settings().persistent_radius_m}
    rows = (await session.execute(_HOTSPOTS, params)).mappings()
    features = [_hotspot_feature(dict(r)) for r in rows if kinds is None or r["kind"] in kinds]
    return {"type": "FeatureCollection", "features": features}


async def fetch_hotspot_summary(session: AsyncSession, query: SpatioTemporalQuery) -> list[dict[str, Any]]:
    params = query.sql_params | {"eps": get_settings().dispatch_cluster_m}
    return [dict(r) for r in (await session.execute(_HOTSPOT_SUMMARY, params)).mappings()]


async def fetch_satellites(session: AsyncSession, query: SpatioTemporalQuery) -> dict[str, int]:
    rows = (await session.execute(_SATELLITES, query.sql_params)).mappings()
    return {r["satellite"]: r["n"] for r in rows}


async def fetch_burn_areas(session: AsyncSession, query: SpatioTemporalQuery) -> dict[str, Any]:
    features = []
    for row in (await session.execute(_BURN_AREAS, query.sql_params)).mappings():
        share = row["area_ha"] / row["full_area_ha"] if row["full_area_ha"] else 0.0
        features.append(
            {
                "type": "Feature",
                "id": row["id"],
                "geometry": json.loads(row["geojson"]),
                "properties": {
                    "contour_id": row["id"],
                    "scene_id": row["scene_id"],
                    "fire_event_id": row["fire_event_id"],
                    "date_pre": row["date_pre"].isoformat(),
                    "date_post": row["date_post"].isoformat(),
                    "area_ha": round(row["area_ha"], 2),
                    "sev1_ha": round(row["sev1_ha"] * share, 2),
                    "sev2_ha": round(row["sev2_ha"] * share, 2),
                    "sev3_ha": round(row["sev3_ha"] * share, 2),
                    "clipped": not row["is_whole"],
                    "area_crs": f"EPSG:{row['epsg']}",
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


async def fetch_severity_polygons(session: AsyncSession, query: SpatioTemporalQuery) -> dict[str, Any]:
    features = [
        {
            "type": "Feature",
            "id": row["id"],
            "geometry": json.loads(row["geojson"]),
            "properties": {
                "polygon_id": row["id"],
                "contour_id": row["burn_area_id"],
                "scene_id": row["scene_id"],
                "fire_event_id": row["fire_event_id"],
                "severity": row["severity"],
                "severity_label": SEVERITY_LABELS[row["severity"]],
                "area_ha": round(row["area_ha"], 3),
                "date_pre": row["date_pre"].isoformat(),
                "date_post": row["date_post"].isoformat(),
                "area_crs": f"EPSG:{row['epsg']}",
            },
        }
        for row in (await session.execute(_SEVERITY_POLYGONS, query.sql_params)).mappings()
    ]
    return {"type": "FeatureCollection", "features": features}


async def fetch_severity_by_scene(session: AsyncSession, query: SpatioTemporalQuery) -> list[dict[str, Any]]:
    return [dict(r) for r in (await session.execute(_SEVERITY_BY_SCENE, query.sql_params)).mappings()]


async def fetch_landcover(
    session: AsyncSession, scene_ids: list[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    crosstab = [dict(r) for r in (await session.execute(_LANDCOVER, {"scene_ids": scene_ids})).mappings()]
    totals = [dict(r) for r in (await session.execute(_SCENE_TOTALS, {"scene_ids": scene_ids})).mappings()]
    return crosstab, totals
