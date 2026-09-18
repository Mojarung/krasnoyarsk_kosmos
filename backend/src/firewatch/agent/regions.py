from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any

AOI_ID = "aoi"
AOI_ALIASES = ("вся территори", "весь регион", "всей территори", "поволж", "подонь", "везде")


@dataclass(frozen=True)
class Region:
    id: str
    name: str
    aliases: tuple[str, ...]
    geometry: dict[str, Any]


def _read(name: str) -> dict[str, Any]:
    return json.loads(resources.files("firewatch.assets").joinpath(name).read_text("utf-8"))


@lru_cache
def all_regions() -> tuple[Region, ...]:
    aoi = _read("aoi.geojson")["features"][0]
    regions = [Region(AOI_ID, aoi["properties"]["name"], AOI_ALIASES, aoi["geometry"])]
    for feature in _read("regions.geojson")["features"]:
        props = feature["properties"]
        regions.append(Region(props["id"], props["name"], tuple(props["aliases"]), feature["geometry"]))
    return tuple(regions)


def find_region(text: str) -> Region | None:
    lowered = text.lower()
    for region in all_regions():
        if region.id == lowered or any(alias in lowered for alias in region.aliases):
            return region
    return None
