"""Поиск сцен Sentinel-2 L2A в открытом STAC-каталоге Earth Search (AWS, без авторизации)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import httpx
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from firewatch.config import get_settings

S2_COLLECTION = "sentinel-2-l2a"
DEM_COLLECTION = "cop-dem-glo-30"
SEARCH_LIMIT = 60
LATTICE_ASSET = "nir08"
# С базовой версии обработки 04.00 ESA прибавляет к отражению 1000. Наборы кейса собраны без сдвига,
# а Earth Search помечает сцены, в которых сдвиг уже снят.
BOA_OFFSET_BASELINE = 4.0
BOA_OFFSET = 1000


class NoImageryError(LookupError):
    pass


@dataclass(frozen=True)
class S2Item:
    id: str
    acquired: datetime
    cloud_cover: float
    epsg: int | None
    footprint: BaseGeometry
    assets: dict[str, str]
    boa_offset: int
    tile: str | None
    origin: tuple[float, float] | None


def _https(href: str) -> str:
    """Публичные бакеты читаются по https, а каталог местами отдаёт ссылки вида s3://bucket/key."""
    if not href.startswith("s3://"):
        return href
    bucket, _, key = href.removeprefix("s3://").partition("/")
    return f"https://{bucket}.s3.amazonaws.com/{key}"


def _epsg(properties: dict[str, Any]) -> int | None:
    if properties.get("proj:epsg"):
        return int(properties["proj:epsg"])
    code = str(properties.get("proj:code", ""))
    return int(code.removeprefix("EPSG:")) if code.startswith("EPSG:") else None


def _origin(feature: dict[str, Any]) -> tuple[float, float] | None:
    """Левый верхний угол тайла в UTM: от него отсчитываются внутренние блоки COG."""
    transform = feature["assets"].get(LATTICE_ASSET, {}).get("proj:transform")
    return (float(transform[2]), float(transform[5])) if transform else None


def parse_s2_item(feature: dict[str, Any]) -> S2Item:
    properties = feature["properties"]
    baseline = float(properties.get("s2:processing_baseline") or 0.0)
    shifted = baseline >= BOA_OFFSET_BASELINE and not properties.get("earthsearch:boa_offset_applied", False)
    return S2Item(
        id=feature["id"],
        acquired=datetime.fromisoformat(properties["datetime"].replace("Z", "+00:00")),
        cloud_cover=float(properties.get("eo:cloud_cover") or 0.0),
        epsg=_epsg(properties),
        footprint=shape(feature["geometry"]),
        assets={name: _https(asset["href"]) for name, asset in feature["assets"].items() if "href" in asset},
        boa_offset=BOA_OFFSET if shifted else 0,
        tile=properties.get("grid:code"),
        origin=_origin(feature),
    )


def _search(body: dict[str, Any]) -> list[dict[str, Any]]:
    settings = get_settings()
    response = httpx.post(f"{settings.stac_url}/search", json=body, timeout=settings.external_timeout_seconds)
    response.raise_for_status()
    return response.json()["features"]


def search_s2(area: BaseGeometry, target: date, days: int) -> list[S2Item]:
    start, end = target - timedelta(days=days), target + timedelta(days=days)
    features = _search(
        {
            "collections": [S2_COLLECTION],
            "intersects": area.__geo_interface__,
            "datetime": f"{start.isoformat()}T00:00:00Z/{end.isoformat()}T23:59:59Z",
            "limit": SEARCH_LIMIT,
        }
    )
    return [parse_s2_item(feature) for feature in features]


def search_dem(area: BaseGeometry) -> list[str]:
    features = _search({"collections": [DEM_COLLECTION], "intersects": area.__geo_interface__, "limit": 9})
    return [_https(feature["assets"]["data"]["href"]) for feature in features]


def rank_items(
    items: list[S2Item], area: BaseGeometry, target: date, chip_epsg: int, tile: str | None = None
) -> list[S2Item]:
    """Сначала сцены, которые закрывают чип целиком, из нужного тайла и родной зоны UTM, затем по облачности и дате."""
    whole = [item for item in items if item.footprint.contains(area)]
    pool = whole or sorted(items, key=lambda item: -item.footprint.intersection(area).area)[:SEARCH_LIMIT]
    return sorted(
        pool,
        key=lambda item: (
            tile is not None and item.tile != tile,
            item.epsg != chip_epsg,
            round(item.cloud_cover / 10.0),
            abs((item.acquired.date() - target).days),
        ),
    )
