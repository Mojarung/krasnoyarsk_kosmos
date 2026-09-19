"""Explainable, query-independent fire events derived from ready observations.

No ground-truth masks are used. AF association is a hypothesis, not an incident
register. Ambiguous matches remain separate. Redis data-version invalidates the
index after ingestion/reprocessing; changing the AOI never changes membership.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from pyproj import Transformer
from scipy.spatial import cKDTree
from shapely.geometry import Point, shape
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from firewatch.infra.cache import cached
from firewatch.services.query import SpatioTemporalQuery
from firewatch.services.restoration import build_plan

AF_RADIUS_M = 1500
AF_GAP_HOURS = 48
BURN_RADIUS_M = 375
INDEX_VERSION = 5
_index_lock = asyncio.Lock()

HOTSPOTS = text("""
    SELECT h.id, h.scene_id, h.acquired_at, h.satellite, h.confidence,
           ST_X(h.geom) AS lon, ST_Y(h.geom) AS lat
    FROM hotspots h JOIN scenes sc ON sc.id=h.scene_id
    WHERE sc.status='ready' AND h.code=1 AND NOT h.persistent
    ORDER BY h.acquired_at, h.scene_id, h.id
""")
SCENES = text("""
    SELECT sc.id, sc.fire_event_id, sc.date_pre, sc.date_post, sc.cloud_frac, sc.epsg,
           coalesce(sum(b.area_ha),0) AS area_ha,
           coalesce(sum(b.sev3_ha),0) AS severe_ha, count(b.id) AS contours
    FROM scenes sc JOIN burn_areas b ON b.scene_id=sc.id
    WHERE sc.status='ready' AND sc.kind='bs'
    GROUP BY sc.id ORDER BY sc.date_post, sc.id
""")
CANDIDATES = text("""
    SELECT h.id AS hotspot_id, b.scene_id,
           min(ST_Distance(h.geom::geography, b.geom::geography)) AS distance_m
    FROM hotspots h JOIN scenes sc ON sc.id=h.scene_id
    JOIN burn_areas b ON b.geom && ST_Expand(h.geom, 0.01)
      AND h.acquired_at >= b.date_pre::timestamp AT TIME ZONE 'UTC'
      AND h.acquired_at < (b.date_post + 1)::timestamp AT TIME ZONE 'UTC'
      AND ST_DWithin(h.geom::geography, b.geom::geography, :radius)
    JOIN scenes bs ON bs.id=b.scene_id AND bs.status='ready'
    WHERE sc.status='ready' AND h.code=1 AND NOT h.persistent
    GROUP BY h.id, b.scene_id
""")


def _timestamp(value: Any) -> float:
    return datetime.fromisoformat(str(value)).timestamp()


def associate(hotspots: list[dict], scenes: list[dict], matches: list[dict]) -> dict:
    """Pure, deterministic association. Spatial chains require a temporal edge."""
    hotspots = [
        h | {"acquired_at": datetime.fromisoformat(str(h["acquired_at"])).isoformat()} for h in hotspots
    ]
    scenes_by_key: dict[str, list[dict]] = defaultdict(list)
    scene_keys = {}
    for s in scenes:
        key = "bs-" + (s.get("fire_event_id") or s["id"])
        scene_keys[s["id"]] = key
        scenes_by_key[key].append(s)
    candidates: dict[int, dict[str, float]] = defaultdict(dict)
    for m in matches:
        key = scene_keys[m["scene_id"]]
        old = candidates[m["hotspot_id"]].get(key, float("inf"))
        candidates[m["hotspot_id"]][key] = min(old, float(m["distance_m"]))

    ordered = sorted(
        hotspots, key=lambda h: (_timestamp(h["acquired_at"]), h["scene_id"], h["lon"], h["lat"])
    )
    parents = list(range(len(ordered)))

    def root(i: int) -> int:
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    if ordered:
        project = Transformer.from_crs(4326, 32638, always_xy=True)
        coords = [project.transform(h["lon"], h["lat"]) for h in ordered]
        times = [_timestamp(h["acquired_at"]) for h in ordered]
        for a, b in sorted(cKDTree(coords).query_pairs(AF_RADIUS_M)):
            if abs(times[a] - times[b]) <= AF_GAP_HOURS * 3600:
                ra, rb = root(a), root(b)
                parents[max(ra, rb)] = min(ra, rb)

    components: dict[int, list[dict]] = defaultdict(list)
    for i, h in enumerate(ordered):
        components[root(i)].append(h)
    event_hotspots: dict[str, list[dict]] = defaultdict(list)
    ambiguities: dict[str, list[str]] = {}
    for group in components.values():
        keys = sorted({k for h in group for k in candidates[h["id"]]})
        if len(keys) == 1:
            key = keys[0]
        else:
            anchor = group[0]
            raw = f"{anchor['scene_id']}:{anchor['acquired_at']}:{anchor['lon']:.7f}:{anchor['lat']:.7f}"
            key = "af-" + hashlib.sha256(raw.encode()).hexdigest()[:16]
            if keys:
                ambiguities[key] = keys
        event_hotspots[key].extend(group)

    events = []
    for key in sorted(scenes_by_key.keys() | event_hotspots.keys()):
        hs = sorted(event_hotspots[key], key=lambda h: (_timestamp(h["acquired_at"]), h["id"]))
        bs = scenes_by_key[key]
        days = sorted({str(h["acquired_at"])[:10] for h in hs})
        dates = days + [str(s[f]) for s in bs for f in ("date_pre", "date_post")]
        status = (
            "ambiguous"
            if key in ambiguities
            else "linked"
            if hs and bs
            else "burn_only"
            if bs
            else "hotspot_only"
        )
        events.append(
            {
                "id": key,
                "status": status,
                "date_from": min(dates),
                "date_to": max(dates),
                "first_seen": str(hs[0]["acquired_at"]) if hs else None,
                "last_seen": str(hs[-1]["acquired_at"]) if hs else None,
                "observed_days": len(days),
                "hotspot_count": len(hs),
                "scene_ids": [s["id"] for s in bs],
                # An overlapping multi-scene area needs the detail union; absence
                # of a Sentinel observation is unknown, never zero hectares.
                "area_ha": round(float(bs[0]["area_ha"]), 2) if len(bs) == 1 else None,
                "candidate_ids": ambiguities.get(key, []),
                "hotspots": hs,
                "scenes": bs,
                "evidence": [
                    {"hotspot_id": h["id"], "distance_m": round(candidates[h["id"]][key], 1)}
                    for h in hs
                    if key in candidates[h["id"]]
                ],
            }
        )
    return {
        "events": events,
        "method": {
            "af_radius_m": AF_RADIUS_M,
            "af_gap_hours": AF_GAP_HOURS,
            "burn_radius_m": BURN_RADIUS_M,
            "association": "Термоточки объединены цепочкой: до 1,5 км и 48 часов между соседними наблюдениями. Связь с гарью предполагается, если точка находится в контуре или не далее 375 м от него и между датами снимков Sentinel. Несколько возможных событий остаются раздельными.",
            "observation": "Это история загруженных снимков. Промежутки между пролётами не подтверждают непрерывное горение, направление фронта или тушение.",
        },
    }


async def index(session: AsyncSession) -> dict:
    async def produce() -> dict:
        hs = [dict(r) for r in (await session.execute(HOTSPOTS)).mappings()]
        bs = [dict(r) for r in (await session.execute(SCENES)).mappings()]
        links = [dict(r) for r in (await session.execute(CANDIDATES, {"radius": BURN_RADIUS_M})).mappings()]
        # Normalise both cold and cached responses to the same JSON contract.
        return await asyncio.to_thread(
            associate, json.loads(json.dumps(hs, default=str)), json.loads(json.dumps(bs, default=str)), links
        )

    async with _index_lock:
        return await cached("event-index", INDEX_VERSION, produce)


def summary(event: dict) -> dict:
    return {k: v for k, v in event.items() if k not in {"hotspots", "scenes", "evidence"}}


def in_query(event: dict, query: SpatioTemporalQuery, matching_scenes: set[str], area=None) -> bool:
    """A matching observation must meet space AND time, not independent extrema."""
    if area is None:
        area = shape(query.geometry)
    start, end = query.date_from.isoformat(), query.date_to.isoformat()
    for h in event["hotspots"]:
        if start <= h["acquired_at"][:10] <= end and area.intersects(Point(h["lon"], h["lat"])):
            return True
    return bool(matching_scenes.intersection(event["scene_ids"]))


async def detail(session: AsyncSession, event: dict, method: dict) -> dict:
    scene_ids = event["scene_ids"]
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [h["lon"], h["lat"]]},
            "properties": {"kind": "hotspot", "id": h["id"]},
        }
        for h in event["hotspots"]
    ]
    burn = None
    restoration = None
    if scene_ids:
        area_epsg = event["scenes"][0]["epsg"]
        if len(scene_ids) == 1:
            # Polygonized classes in one scene are already disjoint. Keep this
            # a separate query: PostgreSQL evaluates aggregates even in an
            # unused CASE branch, making a conditional union just as expensive.
            geometry_sql = """
                WITH projected AS (
                    SELECT severity, ST_Transform(geom,CAST(:epsg AS integer)) AS geom
                    FROM severity_polygons WHERE scene_id=ANY(:ids)
                ) SELECT severity, sum(ST_Area(geom))/10000 AS area_ha,
                    ST_AsGeoJSON(ST_Collect(ST_Transform(ST_SimplifyPreserveTopology(geom,20),4326))) AS geometry
                  FROM projected GROUP BY severity ORDER BY severity
            """
        else:
            geometry_sql = """
                WITH classes AS (
                    SELECT severity, ST_UnaryUnion(ST_Collect(ST_Transform(geom,CAST(:epsg AS integer)))) AS geom
                    FROM severity_polygons WHERE scene_id=ANY(:ids) GROUP BY severity
                ), disjoint AS (
                    SELECT c.severity, ST_Difference(c.geom, coalesce(
                        (SELECT ST_UnaryUnion(ST_Collect(h.geom)) FROM classes h WHERE h.severity>c.severity),
                        ST_GeomFromText('POLYGON EMPTY',CAST(:epsg AS integer)))) AS geom FROM classes c
                ) SELECT severity, ST_Area(geom)/10000 AS area_ha,
                         ST_AsGeoJSON(ST_Transform(ST_SimplifyPreserveTopology(geom,20),4326)) AS geometry
                  FROM disjoint ORDER BY severity
            """
        # Union each class, then higher severity wins overlaps. Never count the
        # same hectare twice if an event spans overlapping Sentinel scenes.
        rows = (
            (
                await session.execute(
                    text(geometry_sql),
                    {"ids": scene_ids, "epsg": area_epsg},
                )
            )
            .mappings()
            .all()
        )
        areas = {r["severity"]: float(r["area_ha"]) for r in rows}
        for r in rows:
            features.append(
                {
                    "type": "Feature",
                    "geometry": json.loads(r["geometry"]),
                    "properties": {"kind": "burn", "severity": r["severity"]},
                }
            )
        total = sum(areas.values())
        burn = {
            "area_ha": round(total, 2),
            "area_crs": f"EPSG:{area_epsg}",
            "by_severity": [
                {
                    "severity": k,
                    "label": label,
                    "area_ha": round(areas.get(k, 0), 2),
                    "share": areas.get(k, 0) / total if total else 0,
                }
                for k, label in ((1, "Слабая"), (2, "Средняя"), (3, "Сильная"))
            ],
        }
        lc = (
            (
                await session.execute(
                    text("""
            SELECT severity, lc_group, sum(area_ha) AS area_ha FROM scar_landcover
            WHERE scene_id=ANY(:ids) GROUP BY severity,lc_group
        """),
                    {"ids": scene_ids},
                )
            )
            .mappings()
            .all()
        )
        raw = defaultdict(float)
        for r in lc:
            raw[r["severity"]] += float(r["area_ha"])
        restoration = build_plan(
            {
                (r["severity"], r["lc_group"]): float(r["area_ha"])
                * areas.get(r["severity"], 0)
                / raw[r["severity"]]
                for r in lc
                if raw[r["severity"]]
            }
        )
        restoration["note"] = (
            "Предварительный план по степени поражения и типу покрова. Для пересекающихся сцен доли покрова нормированы к площади объединения; требуется проверка специалистом."
        )

    observations: dict[str, list[dict]] = defaultdict(list)
    for h in event["hotspots"]:
        observations[h["acquired_at"]].append(h)
    timeline = [
        {
            "at": at,
            "kind": "viirs",
            "hotspot_count": len(hs),
            "satellites": sorted({h["satellite"] for h in hs if h["satellite"]}),
            "scene_ids": sorted({h["scene_id"] for h in hs}),
            "confidence_mean": sum(h["confidence"] for h in hs) / len(hs),
        }
        for at, hs in sorted(observations.items())
    ]
    bounds = [shape(f["geometry"]).bounds for f in features if not shape(f["geometry"]).is_empty]
    bbox = (
        [
            min(b[0] for b in bounds),
            min(b[1] for b in bounds),
            max(b[2] for b in bounds),
            max(b[3] for b in bounds),
        ]
        if bounds
        else None
    )
    return summary(event) | {
        "area_ha": burn["area_ha"] if burn else None,
        "burn": burn,
        "restoration": restoration,
        "timeline": timeline,
        "scenes": [{k: v for k, v in s.items() if k != "footprint"} for s in event["scenes"]],
        "evidence": event["evidence"],
        "method": method,
        "bbox": bbox,
        "map": {"type": "FeatureCollection", "features": features},
        "generated_at": datetime.now(UTC).isoformat(),
        "scope_note": "Паспорт показывает событие целиком, включая связанные наблюдения за границами выбранной территории и периода.",
    }
