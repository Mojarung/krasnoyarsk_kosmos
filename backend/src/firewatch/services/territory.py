"""Опознание территории запроса: про какую местность эта справка.

Справка обязана отвечать на этот вопрос сама, без интерфейса. REST-клиент шлёт
только геометрию и даты - названия региона в запросе нет и быть не может. Поэтому
территория выводится из самой геометрии: сравнением с границей мониторинга и с
границами субъектов из firewatch.assets.

Площади считаются геодезически по эллипсоиду WGS 84 (pyproj.Geod), а не в
градусах: на широте 50° градус долготы вдвое короче градуса широты, и доли
субъектов, посчитанные по плоским координатам, были бы смещены.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Any

from pyproj import Geod
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

GEOD = Geod(ellps="WGS84")

SAME_AREA_IOU = 0.97
"""Выше этого совпадения запрос считается той же фигурой, что эталонная граница."""

SUBJECT_MIN_SHARE = 0.01
"""Субъект попадает в перечень, если занимает хотя бы 1% запроса или 1% своей площади."""

WHOLE_SUBJECT_SHARE = 0.98
"""Выше этой доли субъект считается охваченным целиком."""

KIND_LABELS = {
    "aoi": "Вся территория мониторинга",
    "region": "Субъект Российской Федерации целиком",
    "bbox": "Ограничивающий прямоугольник",
    "polygon": "Произвольный полигон",
}


@lru_cache
def _asset(name: str) -> dict[str, Any]:
    return json.loads(resources.files("firewatch.assets").joinpath(name).read_text("utf-8"))


@lru_cache
def _aoi() -> tuple[BaseGeometry, dict[str, Any]]:
    feature = _asset("aoi.geojson")["features"][0]
    return shape(feature["geometry"]), feature["properties"]


@lru_cache
def _regions() -> tuple[tuple[BaseGeometry, dict[str, Any]], ...]:
    return tuple((shape(f["geometry"]), f["properties"]) for f in _asset("regions.geojson")["features"])


def area_km2(geom: BaseGeometry) -> float:
    """Геодезическая площадь на эллипсоиде. Для дырявых и многоконтурных фигур тоже верна."""
    return abs(GEOD.geometry_area_perimeter(geom)[0]) / 1e6


def _iou(a: BaseGeometry, b: BaseGeometry) -> float:
    union = a.union(b).area
    return a.intersection(b).area / union if union else 0.0


def _is_rectangle(geometry: dict[str, Any]) -> bool:
    if geometry.get("type") != "Polygon" or len(geometry["coordinates"]) != 1:
        return False
    ring = geometry["coordinates"][0]
    if len(ring) != 5:
        return False
    return len({round(x, 6) for x, _ in ring}) == 2 and len({round(y, 6) for _, y in ring}) == 2


def _degrees(value: float, positive: str, negative: str) -> str:
    number = f"{abs(value):.2f}".replace(".", ",")
    return f"{number}° {positive if value >= 0 else negative}"


def _bbox_label(bounds: tuple[float, float, float, float]) -> str:
    west, south, east, north = bounds
    lon = f"{_degrees(west, 'в.д.', 'з.д.')} - {_degrees(east, 'в.д.', 'з.д.')}"
    lat = f"{_degrees(south, 'с.ш.', 'ю.ш.')} - {_degrees(north, 'с.ш.', 'ю.ш.')}"
    return f"{lon}, {lat}"


def _subjects(geom: BaseGeometry, query_area: float) -> list[dict[str, Any]]:
    found = []
    for region, props in _regions():
        if not geom.intersects(region):
            continue
        overlap = geom.intersection(region)
        if overlap.is_empty:
            continue
        overlap_area = area_km2(overlap)
        subject_area = area_km2(region)
        share_of_query = overlap_area / query_area if query_area else 0.0
        share_of_subject = overlap_area / subject_area if subject_area else 0.0
        if share_of_query < SUBJECT_MIN_SHARE and share_of_subject < SUBJECT_MIN_SHARE:
            continue
        found.append(
            {
                "id": props["id"],
                "name": props["name"],
                "name_in": props.get("name_in", props["name"]),
                "area_km2": round(overlap_area, 1),
                "share_of_query": round(share_of_query, 4),
                "share_of_subject": round(share_of_subject, 4),
                "whole": share_of_subject >= WHOLE_SUBJECT_SHARE,
            }
        )
    return sorted(found, key=lambda s: -s["area_km2"])


def _title(kind: str, subjects: list[dict[str, Any]], aoi_props: dict[str, Any], matched: str | None) -> str:
    if kind == "aoi":
        return aoi_props["name"]
    if kind == "region" and matched:
        return matched
    if not subjects:
        return "Участок вне территории мониторинга"
    if len(subjects) == 1:
        return f"Участок {subjects[0]['name_in']}"
    whole = [s for s in subjects if s["whole"]]
    if len(whole) == len(subjects):
        return f"{len(subjects)} субъекта РФ целиком" if len(subjects) < 5 else "Все субъекты территории"
    return f"Участок на территории {len(subjects)} субъектов РФ"


def _rings(geom: BaseGeometry, tolerance: float = 0.02) -> list[list[tuple[float, float]]]:
    """Внешние кольца фигуры для отрисовки. Упрощение 0,02° - это около 2 км:
    на мини-карте шириной 88 мм такая точность за пределами разрешения печати."""
    simple = geom.simplify(tolerance)
    parts = simple.geoms if simple.geom_type == "MultiPolygon" else [simple]
    return [list(part.exterior.coords) for part in parts if not part.is_empty]


def _short(name: str) -> str:
    words = name.split()
    return words[1] if words[0] == "Республика" and len(words) > 1 else words[0]


def map_outlines() -> dict[str, Any]:
    """Контуры для обзорной карты в справке: граница мониторинга и субъекты с точками подписи."""
    aoi_geom, _ = _aoi()
    regions = []
    for geom, props in _regions():
        point = geom.representative_point()
        regions.append(
            {
                "id": props["id"],
                "short": _short(props["name"]),
                "rings": _rings(geom),
                "label_at": (point.x, point.y),
            }
        )
    return {"aoi": _rings(aoi_geom, tolerance=0.0), "regions": regions}


def describe(geometry: dict[str, Any]) -> dict[str, Any]:
    """Паспорт территории запроса: название, тип, координаты, охваченные субъекты."""
    geom = shape(geometry)
    aoi_geom, aoi_props = _aoi()
    query_area = area_km2(geom)
    subjects = _subjects(geom, query_area)

    kind, matched = ("bbox" if _is_rectangle(geometry) else "polygon"), None
    if _iou(geom, aoi_geom) >= SAME_AREA_IOU:
        kind = "aoi"
    else:
        for region, props in _regions():
            if _iou(geom, region) >= SAME_AREA_IOU:
                kind, matched = "region", props["name"]
                break

    inside = geom.intersection(aoi_geom)
    inside_km2 = area_km2(inside) if not inside.is_empty else 0.0
    covered = inside_km2 / query_area if query_area else 0.0

    return {
        "name": _title(kind, subjects, aoi_props, matched),
        "kind": kind,
        "kind_label": KIND_LABELS[kind],
        "area_km2": round(query_area, 1),
        "bbox": [round(v, 4) for v in geom.bounds],
        "bbox_label": _bbox_label(geom.bounds),
        "center": [round(geom.centroid.x, 4), round(geom.centroid.y, 4)],
        "crs": "EPSG:4326 (WGS 84), градусы",
        "area_crs": aoi_props["utm_zones"],
        "subjects": subjects,
        "monitoring_area": {
            "name": aoi_props["name"],
            "subjects": aoi_props["subjects"],
            "area_km2": aoi_props["area_km2"],
            "seasons": aoi_props["seasons"],
            "months": aoi_props["months"],
            "covered_share": round(covered, 4),
            "covered_km2": round(inside_km2, 1),
        },
    }
