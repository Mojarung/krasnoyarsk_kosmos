"""Карточка реагирования на очаг: приоритет, прогноз фронта, что под угрозой и чем тушить.

Здесь только расчёт. Очаги из PostGIS и внешние справочники собирает response_plan.py.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from importlib import resources
from typing import Any

from pyproj import Geod
from shapely.geometry import Point, Polygon, mapping

from firewatch.domain.catalog import LC_GROUP_LABELS

ELLIPSE_VERTICES = 48
KELVIN_OFFSET = 273.15
_GEOD = Geod(ellps="WGS84")


@dataclass(frozen=True)
class FireCluster:
    day: date
    last_seen: datetime
    lon: float
    lat: float
    hotspots: int
    prev_hotspots: int
    frp_mw: float | None
    frp_max_mw: float | None
    landcover: str
    wind_speed: float | None
    rh2m: float | None
    t2m: float | None
    is_night: bool
    hull_m2: float


@dataclass(frozen=True)
class Place:
    name: str
    kind: str
    lon: float
    lat: float


@dataclass(frozen=True)
class GeoContext:
    settlements: list[Place]
    fire_stations: list[Place]
    water: list[Place]
    road_km: float | None


@lru_cache
def load_rules() -> dict[str, Any]:
    return json.loads(resources.files("firewatch.assets").joinpath("response_rules.json").read_text("utf-8"))


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def distance_km(lon_a: float, lat_a: float, lon_b: float, lat_b: float) -> float:
    return _GEOD.inv(lon_a, lat_a, lon_b, lat_b)[2] / 1000.0


def heading_from_wind(wind_dir_deg: float) -> float:
    """Метеорологическое направление - откуда дует. Фронт уходит в противоположную сторону."""
    return (wind_dir_deg + 180.0) % 360.0


def spread_rate_kmh(group: str, wind_ms: float | None, rh: float | None) -> float | None:
    if wind_ms is None:
        return None
    rules = load_rules()["spread"]
    share = rules["wind_share"].get(group, rules["wind_share"]["other"])
    if share == 0.0:
        return 0.0
    dryness = 1.0 if rh is None else _clip((rules["damp_rh"] - rh) / (rules["damp_rh"] - rules["dry_rh"]))
    moisture = rules["damp_factor"] + (1.0 - rules["damp_factor"]) * dryness
    return max(share * wind_ms * 3.6 * moisture, rules["min_kmh"])


def cluster_radius_m(hull_m2: float) -> float:
    return max(math.sqrt(hull_m2 / math.pi), load_rules()["spread"]["min_radius_m"])


def spread_ellipse(
    lon: float, lat: float, *, heading_deg: float, head_km: float, radius_m: float, wind_ms: float
) -> dict[str, Any]:
    """Эллипс возможного выгорания: вытянут по ветру, тыл и фланги идут медленнее фронта."""
    rules = load_rules()["spread"]
    ratio = rules["length_to_breadth"]
    length_to_breadth = _clip(ratio["base"] + ratio["per_ms"] * wind_ms, ratio["min"], ratio["max"])
    head = head_km * 1000.0 + radius_m
    back = head_km * 1000.0 * rules["back_share"] + radius_m
    semi_major = (head + back) / 2.0
    semi_minor = max(semi_major / length_to_breadth, radius_m)
    shift = (head - back) / 2.0

    ring = []
    for step in range(ELLIPSE_VERTICES):
        angle = 2.0 * math.pi * step / ELLIPSE_VERTICES
        along, across = shift + semi_major * math.cos(angle), semi_minor * math.sin(angle)
        azimuth = heading_deg + math.degrees(math.atan2(across, along))
        point_lon, point_lat, _ = _GEOD.fwd(lon, lat, azimuth, math.hypot(along, across))
        ring.append((round(point_lon, 6), round(point_lat, 6)))
    return mapping(Polygon(ring))


def _growth(cluster: FireCluster) -> tuple[str, float]:
    table = load_rules()["priority"]["growth"]
    if cluster.prev_hotspots == 0:
        return "new", table["new"]
    ratio = cluster.hotspots / cluster.prev_hotspots
    if ratio >= 2.0:
        return "doubling", table["doubling"]
    if ratio >= 1.0:
        return "steady", table["steady"]
    return "fading", table["fading"]


def priority(cluster: FireCluster, *, ros_kmh: float | None, exposure: float) -> dict[str, Any]:
    rules = load_rules()["priority"]
    weights = rules["weights"]
    wind = _clip((cluster.wind_speed or 0.0) / rules["wind_full_ms"])
    dryness = 0.5 if cluster.rh2m is None else _clip(1.0 - cluster.rh2m / load_rules()["spread"]["damp_rh"])
    shares = {
        "intensity": _clip(
            math.log10(1.0 + (cluster.frp_mw or 0.0)) / math.log10(1.0 + rules["frp_full_mw"])
        ),
        "size": _clip(cluster.hotspots / rules["size_full_px"]),
        "growth": _growth(cluster)[1],
        "weather": 0.6 * wind + 0.4 * dryness,
        "fuel": rules["fuel"].get(cluster.landcover, rules["fuel"]["other"]),
        "exposure": _clip(exposure),
    }
    parts = {name: round(weights[name] * share, 1) for name, share in shares.items()}
    score = round(sum(parts.values()), 1)
    level = next(item for item in rules["levels"] if score >= item["min"])
    return {"score": score, "level": level["level"], "label": level["label"], "parts": parts}


def choose_method(cluster: FireCluster, ros_kmh: float | None) -> str:
    rules = load_rules()["tactics"]
    if cluster.landcover == "wetland":
        return "wetland"
    intense = (cluster.frp_max_mw or 0.0) >= rules["intense_frp_mw"] or (cluster.wind_speed or 0.0) >= rules[
        "intense_wind_ms"
    ]
    if cluster.landcover in ("forest", "shrub"):
        return "forest_indirect" if intense else "forest_direct"
    fast = ros_kmh is not None and ros_kmh >= rules["fast_front_kmh"]
    return "grass_indirect" if fast or intense else "grass_direct"


def _nearest(places: list[Place], lon: float, lat: float) -> tuple[Place, float] | None:
    ranked = sorted(((distance_km(lon, lat, p.lon, p.lat), p) for p in places), key=lambda pair: pair[0])
    return (ranked[0][1], ranked[0][0]) if ranked else None


def _threats(
    cluster: FireCluster, ellipses: list[dict[str, Any]], settlements: list[Place]
) -> tuple[list[dict[str, Any]], float]:
    rules = load_rules()["priority"]
    shapes = [(item["hours"], Polygon(item["geometry"]["coordinates"][0])) for item in ellipses]
    threats, exposure = [], 0.0
    for place in settlements:
        horizon = next((hours for hours, area in shapes if area.contains(Point(place.lon, place.lat))), None)
        km = distance_km(cluster.lon, cluster.lat, place.lon, place.lat)
        if horizon is None and km > rules["near_km"]:
            continue
        factor = rules["exposure_by_horizon"][str(horizon)] if horizon else rules["exposure_near"]
        exposure = max(exposure, factor)
        threats.append(
            {
                "name": place.name,
                "kind": place.kind,
                "lon": place.lon,
                "lat": place.lat,
                "distance_km": round(km, 1),
                "horizon_h": horizon,
            }
        )
    threats.sort(key=lambda t: (t["horizon_h"] is None, t["horizon_h"] or 0, t["distance_km"]))
    return threats, exposure


def _arrival(cluster: FireCluster, stations: list[Place]) -> dict[str, Any] | None:
    rules = load_rules()["tactics"]
    nearest = _nearest(stations, cluster.lon, cluster.lat)
    if nearest is None:
        return None
    station, km = nearest
    return {
        "station": station.name,
        "lon": station.lon,
        "lat": station.lat,
        "distance_km": round(km, 1),
        "eta_min": round(km * rules["arrival_detour"] / rules["arrival_speed_kmh"] * 60.0),
    }


def _steps(
    cluster: FireCluster,
    method: dict[str, Any],
    threats: list[dict[str, Any]] | None,
    context: GeoContext | None,
) -> list[str]:
    rules = load_rules()["tactics"]
    notes = rules["modifiers"]
    head, tail = [], []
    for threat in threats or []:
        if threat["horizon_h"] is not None:
            head.append(notes["settlement"].format(name=threat["name"], hours=threat["horizon_h"]))
            break
    if context is not None:
        if context.road_km is not None and context.road_km >= rules["remote_road_km"]:
            head.append(notes["remote"].format(km=f"{context.road_km:.1f}".replace(".", ",")))
        water = _nearest(context.water, cluster.lon, cluster.lat)
        if water is not None and water[1] <= rules["water_near_km"]:
            tail.append(notes["water"].format(name=water[0].name, km=f"{water[1]:.1f}".replace(".", ",")))
    if cluster.is_night:
        tail.append(notes["night"])
    return [*head, *method["steps"], *tail]


def build_card(
    cluster: FireCluster, *, wind_dir_deg: float | None, context: GeoContext | None
) -> dict[str, Any]:
    """context=None значит, что OpenStreetMap не ответил: карточка строится без угроз и подъезда."""
    rules = load_rules()
    ros = spread_rate_kmh(cluster.landcover, cluster.wind_speed, cluster.rh2m)
    radius = cluster_radius_m(cluster.hull_m2)

    ellipses: list[dict[str, Any]] = []
    if ros is not None and wind_dir_deg is not None and cluster.wind_speed is not None:
        heading = heading_from_wind(wind_dir_deg)
        ellipses = [
            {
                "hours": hours,
                "head_km": round(ros * hours, 1),
                "geometry": spread_ellipse(
                    cluster.lon,
                    cluster.lat,
                    heading_deg=heading,
                    head_km=ros * hours,
                    radius_m=radius,
                    wind_ms=cluster.wind_speed,
                ),
            }
            for hours in rules["spread"]["horizons_h"]
        ]

    threats, exposure = (None, 0.0) if context is None else _threats(cluster, ellipses, context.settlements)
    key = choose_method(cluster, ros)
    method = rules["tactics"]["methods"][key]
    growth, _ = _growth(cluster)
    temperature = cluster.t2m
    if temperature is not None and temperature > 200:
        temperature -= KELVIN_OFFSET
    return {
        "id": f"{cluster.day:%Y%m%d}-{cluster.lon:.3f}-{cluster.lat:.3f}",
        "day": cluster.day.isoformat(),
        "last_seen": cluster.last_seen.isoformat(),
        "lon": round(cluster.lon, 5),
        "lat": round(cluster.lat, 5),
        "hotspots": cluster.hotspots,
        "prev_hotspots": cluster.prev_hotspots,
        "growth": growth,
        "frp_mw": None if cluster.frp_mw is None else round(cluster.frp_mw, 1),
        "frp_max_mw": None if cluster.frp_max_mw is None else round(cluster.frp_max_mw, 1),
        "landcover": cluster.landcover,
        "landcover_label": LC_GROUP_LABELS[cluster.landcover],
        "is_night": cluster.is_night,
        "weather": {
            "wind_ms": None if cluster.wind_speed is None else round(cluster.wind_speed, 1),
            "wind_dir_deg": None if wind_dir_deg is None else round(wind_dir_deg),
            "rh2m": None if cluster.rh2m is None else round(cluster.rh2m),
            "t2m_c": None if temperature is None else round(temperature, 1),
        },
        "priority": priority(cluster, ros_kmh=ros, exposure=exposure),
        "spread": {
            "rate_kmh": None if ros is None else round(ros, 2),
            "heading_deg": None if wind_dir_deg is None else round(heading_from_wind(wind_dir_deg)),
            "ellipses": ellipses,
        },
        "threats": threats,
        "arrival": None if context is None else _arrival(cluster, context.fire_stations),
        "road_km": None if context is None or context.road_km is None else round(context.road_km, 1),
        "method": {"key": key, "label": method["label"], "resources": method["resources"]},
        "steps": _steps(cluster, method, threats, context),
    }
