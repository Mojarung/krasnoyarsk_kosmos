from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from firewatch.config import get_settings
from firewatch.domain.catalog import lc_group
from firewatch.infra import geodata
from firewatch.services import response as rp
from firewatch.services.query import CLUSTER_EPSG, QUERY_GEOM, SpatioTemporalQuery

_NATURAL = "h.code = 1 AND NOT h.persistent"
_IN_QUERY = (
    "ST_Intersects(h.geom, q.geom) AND h.acquired_at >= :date_from AND h.acquired_at < :date_to_exclusive"
)

# Оперативный план нужен по свежим очагам. В архивном запросе «свежие» - последние дни периода,
# в которые спутник видел природное горение.
_CLUSTERS = text(
    f"""
    WITH q AS (SELECT {QUERY_GEOM} AS geom),
    last AS (SELECT max(h.acquired_at::date) AS day FROM hotspots h CROSS JOIN q WHERE {_IN_QUERY} AND {_NATURAL}),
    pts AS (
        SELECT h.geom, h.frp_mw, h.landcover, h.wind_speed, h.rh2m, h.t2m, h.is_night, h.acquired_at,
               h.acquired_at::date AS day,
               ST_ClusterDBSCAN(ST_Transform(h.geom, {CLUSTER_EPSG}), eps := :eps, minpoints := 1)
                   OVER (PARTITION BY h.acquired_at::date) AS cluster_id
        FROM hotspots h CROSS JOIN q CROSS JOIN last
        WHERE {_IN_QUERY} AND {_NATURAL} AND h.acquired_at::date > last.day - CAST(:window AS integer)
    ),
    fires AS (
        SELECT day, max(acquired_at) AS last_seen, count(*) AS hotspots, sum(frp_mw) AS frp_mw,
               max(frp_mw) AS frp_max_mw, mode() WITHIN GROUP (ORDER BY landcover) AS landcover,
               avg(wind_speed) AS wind_speed, avg(rh2m) AS rh2m, avg(t2m) AS t2m, bool_or(is_night) AS is_night,
               ST_Centroid(ST_Collect(geom)) AS center,
               ST_Area(ST_ConvexHull(ST_Collect(ST_Transform(geom, {CLUSTER_EPSG})))) AS hull_m2
        FROM pts GROUP BY day, cluster_id
    )
    SELECT f.*, ST_X(f.center) AS lon, ST_Y(f.center) AS lat,
           (SELECT count(*) FROM hotspots h
            WHERE {_NATURAL} AND h.acquired_at >= f.day - 1 AND h.acquired_at < f.day
              AND ST_DWithin(h.geom::geography, f.center::geography, CAST(:growth_radius AS double precision))) AS prev_hotspots
    FROM fires f
    """
)


def _cluster(row: dict[str, Any]) -> rp.FireCluster:
    return rp.FireCluster(
        day=row["day"],
        last_seen=row["last_seen"],
        lon=row["lon"],
        lat=row["lat"],
        hotspots=row["hotspots"],
        prev_hotspots=row["prev_hotspots"],
        frp_mw=row["frp_mw"],
        frp_max_mw=row["frp_max_mw"],
        landcover=lc_group(row["landcover"]),
        wind_speed=row["wind_speed"],
        rh2m=row["rh2m"],
        t2m=row["t2m"],
        is_night=row["is_night"],
        hull_m2=row["hull_m2"],
    )


def _context(raw: dict[str, Any] | None) -> rp.GeoContext | None:
    if raw is None:
        return None
    return rp.GeoContext(
        settlements=[rp.Place(**p) for p in raw["settlements"]],
        fire_stations=[rp.Place(**p) for p in raw["fire_stations"]],
        water=[rp.Place(**p) for p in raw["water"]],
        road_km=raw["road_km"],
    )


def _reach_km(cluster: rp.FireCluster) -> float:
    rules = rp.load_rules()
    ros = rp.spread_rate_kmh(cluster.landcover, cluster.wind_speed, cluster.rh2m) or 0.0
    return ros * max(rules["spread"]["horizons_h"]) + rules["priority"]["near_km"]


async def _card(cluster: rp.FireCluster, raw: dict[str, Any] | None) -> dict[str, Any]:
    """raw=None - OpenStreetMap не ответил или очаг вне верхушки списка."""
    wind = await geodata.wind_at(cluster.lon, cluster.lat, cluster.last_seen)
    if cluster.wind_speed is None and wind:
        cluster = replace(cluster, wind_speed=wind["speed_ms"])
    return rp.build_card(cluster, wind_dir_deg=wind["direction_deg"] if wind else None, context=_context(raw))


async def build_response_plan(session: AsyncSession, query: SpatioTemporalQuery) -> dict[str, Any]:
    settings = get_settings()
    params = query.sql_params | {
        "eps": settings.dispatch_cluster_m,
        "window": settings.response_window_days,
        "growth_radius": settings.response_growth_radius_m,
    }
    clusters = [_cluster(dict(r)) for r in (await session.execute(_CLUSTERS, params)).mappings()]

    # Публичный Overpass отвечает десятки секунд и режет частые запросы, поэтому окружение спрашиваем
    # одним запросом и только у самых опасных очагов.
    def rough(cluster: rp.FireCluster) -> float:
        ros = rp.spread_rate_kmh(cluster.landcover, cluster.wind_speed, cluster.rh2m)
        return rp.priority(cluster, ros_kmh=ros, exposure=0.0)["score"]

    top = sorted(clusters, key=rough, reverse=True)[: settings.response_max_clusters]
    exposed = top[: settings.response_osm_clusters]
    context, osm_status = await geodata.surroundings([(c.lon, c.lat, _reach_km(c)) for c in exposed])
    around = [*context, *([None] * len(top))][: len(top)]
    cards = await asyncio.gather(*(_card(cluster, raw) for cluster, raw in zip(top, around, strict=True)))
    cards = sorted(cards, key=lambda card: -card["priority"]["score"])

    rules = rp.load_rules()
    levels = {item["level"]: 0 for item in rules["priority"]["levels"]}
    for card in cards:
        levels[card["priority"]["level"]] += 1
    days = sorted({c.day for c in clusters})
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "window": {
            "from": days[0].isoformat() if days else None,
            "to": days[-1].isoformat() if days else None,
            "days": settings.response_window_days,
        },
        "fires_total": len(clusters),
        "by_level": levels,
        "external": {
            "wind": any(card["weather"]["wind_dir_deg"] is not None for card in cards),
            "osm": osm_status,
        },
        "cards": cards,
        "disclaimer": rules["disclaimer"],
        "sources": rules["sources"],
    }
