"""Import VIIRS active-fire detections from the official NASA FIRMS Area API."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx
from geoalchemy2.shape import from_shape
from pyproj import Transformer
from shapely.geometry import Point, box
from shapely.geometry.base import BaseGeometry
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from firewatch.config import get_settings
from firewatch.db.models import Hotspot, Scene
from firewatch.infra.cache import bump_data_version
from firewatch.pipeline.acquire import utm_epsg

MAX_API_DAYS = 5
PRODUCTS = {
    "SNPP": ("VIIRS_SNPP_SP", "VIIRS_SNPP_NRT"),
    "NOAA20": ("VIIRS_NOAA20_SP", "VIIRS_NOAA20_NRT"),
    "NOAA21": ("VIIRS_NOAA21_SP", "VIIRS_NOAA21_NRT"),
}
SATELLITES = {
    "N": "SNPP",
    "SNPP": "SNPP",
    "S-NPP": "SNPP",
    "N20": "NOAA20",
    "NOAA20": "NOAA20",
    "NOAA-20": "NOAA20",
    "N21": "NOAA21",
    "NOAA21": "NOAA21",
    "NOAA-21": "NOAA21",
}
CONFIDENCE = {"l": 0.33, "low": 0.33, "n": 0.66, "nominal": 0.66, "h": 1.0, "high": 1.0}


class FirmsError(RuntimeError):
    pass


@dataclass(frozen=True)
class Availability:
    product: str
    date_from: date
    date_to: date


@dataclass(frozen=True)
class RequestPart:
    product: str
    date_from: date
    days: int


@dataclass(frozen=True)
class Detection:
    external_id: str
    lon: float
    lat: float
    acquired_at: datetime
    satellite: str
    bt_i4: float
    bt_i5: float
    frp_mw: float | None
    confidence: float
    is_night: bool


def _float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except ValueError:
        return default


def parse_availability(body: str) -> list[Availability]:
    rows = []
    for row in csv.DictReader(io.StringIO(body.lstrip("\ufeff"))):
        product = (row.get("data_id") or "").strip().upper()
        try:
            rows.append(
                Availability(
                    product=product,
                    date_from=date.fromisoformat((row.get("min_date") or "").strip()),
                    date_to=date.fromisoformat((row.get("max_date") or "").strip()),
                )
            )
        except ValueError:
            continue
    if not rows:
        raise FirmsError("NASA FIRMS не вернул сведения о доступности данных")
    return rows


def plan_requests(availability: list[Availability], date_from: date, date_to: date) -> list[RequestPart]:
    """Pick Standard Processing first, then NRT, without requesting the same sensor twice."""
    by_product = {item.product: item for item in availability}
    result = []
    for products in PRODUCTS.values():
        current = date_from
        while current <= date_to:
            candidate = next(
                (
                    by_product[product]
                    for product in products
                    if product in by_product and by_product[product].date_from <= current <= by_product[product].date_to
                ),
                None,
            )
            if candidate is None:
                starts = [
                    by_product[product].date_from
                    for product in products
                    if product in by_product and by_product[product].date_from > current
                ]
                if not starts:
                    break
                current = min(starts)
                continue
            end = min(date_to, candidate.date_to, current + timedelta(days=MAX_API_DAYS - 1))
            result.append(RequestPart(candidate.product, current, (end - current).days + 1))
            current = end + timedelta(days=1)
    return result


def parse_detections(body: str, product: str) -> list[Detection]:
    reader = csv.DictReader(io.StringIO(body.lstrip("\ufeff")))
    fields = {field.lower() for field in (reader.fieldnames or [])}
    if not {"latitude", "longitude", "acq_date", "acq_time"}.issubset(fields):
        detail = body.strip().replace("\n", " ")[:180]
        raise FirmsError(f"NASA FIRMS вернул неожиданный ответ: {detail or 'пустой ответ'}")
    fallback = next((sensor for sensor, products in PRODUCTS.items() if product in products), "VIIRS")
    result = []
    for row in reader:
        try:
            lon, lat = float(row["longitude"]), float(row["latitude"])
            raw_time = (row.get("acq_time") or "0").strip().zfill(4)
            acquired_at = datetime.strptime(
                f"{row['acq_date']} {raw_time[:2]}:{raw_time[2:4]}", "%Y-%m-%d %H:%M"
            ).replace(tzinfo=UTC)
        except (KeyError, ValueError):
            continue
        satellite = SATELLITES.get((row.get("satellite") or "").strip().upper(), fallback)
        raw_confidence = (row.get("confidence") or "n").strip().lower()
        confidence = CONFIDENCE.get(raw_confidence, min(1.0, max(0.0, _float(raw_confidence) / 100)))
        identity = f"{satellite}:{acquired_at.isoformat()}:{lat:.5f}:{lon:.5f}"
        result.append(
            Detection(
                external_id="firms:" + hashlib.sha256(identity.encode()).hexdigest()[:40],
                lon=lon,
                lat=lat,
                acquired_at=acquired_at,
                satellite=satellite,
                bt_i4=_float(row.get("bright_ti4")),
                bt_i5=_float(row.get("bright_ti5")),
                frp_mw=_float(row.get("frp")) if row.get("frp") not in (None, "") else None,
                confidence=confidence,
                is_night=(row.get("daynight") or "D").strip().upper() == "N",
            )
        )
    return result


async def _csv(client: httpx.AsyncClient, path: str) -> str:
    response = await client.get(path)
    response.raise_for_status()
    return response.text


async def fetch(area: BaseGeometry, date_from: date, date_to: date) -> tuple[list[Detection], list[str]]:
    settings = get_settings()
    if not settings.firms_map_key:
        raise FirmsError("Для загрузки термоточек укажите FIRMS_MAP_KEY в .env")
    span_days = (date_to - date_from).days
    if span_days < 0:
        raise FirmsError("Начало периода должно быть раньше окончания")

    base = settings.firms_base_url.rstrip("/")
    key = quote(settings.firms_map_key, safe="")
    west, south, east, north = area.bounds
    bounds = ",".join(f"{value:.5f}" for value in (west, south, east, north))
    timeout = httpx.Timeout(45.0, connect=10.0)
    async with httpx.AsyncClient(base_url=base, timeout=timeout, follow_redirects=True) as client:
        availability = parse_availability(await _csv(client, f"/api/data_availability/csv/{key}/all"))
        requests = plan_requests(availability, date_from, date_to)
        semaphore = asyncio.Semaphore(6)

        async def load(part: RequestPart) -> tuple[list[Detection], str]:
            async with semaphore:
                path = f"/api/area/csv/{key}/{part.product}/{bounds}/{part.days}/{part.date_from.isoformat()}"
                return parse_detections(await _csv(client, path), part.product), part.product

        batches = await asyncio.gather(*(load(part) for part in requests))

    # The Area API accepts only a bbox. Honour the polygon the user actually drew.
    prepared = area.buffer(0)
    detections = {
        item.external_id: item
        for batch, _ in batches
        for item in batch
        if prepared.intersects(Point(item.lon, item.lat))
    }
    return list(detections.values()), sorted({product for _, product in batches})


def _scene_id(detection: Detection, area: BaseGeometry) -> str:
    bounds = ",".join(f"{value:.4f}" for value in area.bounds)
    digest = hashlib.sha256(bounds.encode()).hexdigest()[:8]
    return f"AF_firms_{detection.satellite}_{detection.acquired_at:%Y%m%d}_{digest}"


async def import_hotspots(
    session: AsyncSession, area: BaseGeometry, date_from: date, date_to: date
) -> dict[str, Any]:
    detections, products = await fetch(area, date_from, date_to)
    if not detections:
        return {"status": "ready", "imported": 0, "existing": 0, "products": products}

    external_ids = [item.external_id for item in detections]
    existing = set(
        (await session.execute(select(Hotspot.external_id).where(Hotspot.external_id.in_(external_ids)))).scalars()
    )
    fresh = [item for item in detections if item.external_id not in existing]
    grouped: dict[str, list[Detection]] = defaultdict(list)
    for item in fresh:
        grouped[_scene_id(item, area)].append(item)

    footprint = box(*area.bounds)
    for scene_id, items in grouped.items():
        first = items[0]
        epsg = utm_epsg(first.lon, first.lat)
        scene = await session.get(Scene, scene_id)
        if scene is None:
            scene = Scene(
                id=scene_id,
                kind="af",
                status="ready",
                source="firms",
                epsg=epsg,
                footprint=from_shape(footprint, srid=4326),
                acquired_at=min(item.acquired_at for item in items),
                satellite=first.satellite,
                files={},
                quicklooks={},
                model_name="NASA FIRMS VIIRS C2",
                stats={"provider": "NASA FIRMS", "detections": len(items)},
                processed_at=datetime.now(UTC),
            )
            session.add(scene)
            await session.flush()
        transformers: dict[int, Transformer] = {}
        for item in items:
            point_epsg = utm_epsg(item.lon, item.lat)
            transformer = transformers.setdefault(
                point_epsg, Transformer.from_crs(4326, point_epsg, always_xy=True)
            )
            x, y = transformer.transform(item.lon, item.lat)
            session.add(
                Hotspot(
                    external_id=item.external_id,
                    scene_id=scene_id,
                    geom=f"SRID=4326;POINT({item.lon} {item.lat})",
                    epsg=point_epsg,
                    x_utm=round(x),
                    y_utm=round(y),
                    acquired_at=item.acquired_at,
                    satellite=item.satellite,
                    code=1,
                    persistent=False,
                    bt_i4=item.bt_i4,
                    bt_i5=item.bt_i5,
                    frp_mw=item.frp_mw,
                    confidence=item.confidence,
                    landcover=0,
                    is_night=item.is_night,
                    t2m=None,
                    rh2m=None,
                    wind_speed=None,
                )
            )
    await session.commit()
    if fresh:
        await bump_data_version()
    return {
        "status": "ready",
        "imported": len(fresh),
        "existing": len(detections) - len(fresh),
        "products": products,
    }
