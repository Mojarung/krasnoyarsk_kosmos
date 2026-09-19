"""On-demand, non-overlapping restoration zones from published severity and land cover."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from importlib import resources

import numpy as np
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.features import rasterize, shapes
from rasterio.io import MemoryFile
from rasterio.vrt import WarpedVRT
from shapely import make_valid
from shapely.errors import GEOSException
from shapely.geometry import mapping, shape
from shapely.ops import clip_by_rect, transform, unary_union
from shapely.prepared import prep
from sqlalchemy import text

from firewatch.domain.catalog import LC_GROUP_BY_CODE, LC_GROUP_LABELS, SEVERITY_LABELS
from firewatch.infra import s3
from firewatch.infra.broker import WORK_MAP_QUEUE, broker
from firewatch.infra.cache import redis
from firewatch.services.vegetation import make_grid, now, unlock

VERSION = 1
LABELS = {
    "planting": "Проверить под посадку",
    "assisted": "Содействие восстановлению",
    "natural": "Наблюдение",
    "agro": "Агротехнические работы",
    "erosion": "Контроль эрозии",
    "none": "Без мероприятий",
    "unknown": "Недостаточно данных",
}


def rules() -> dict:
    return json.loads(resources.files("firewatch.assets").joinpath("restoration_rules.json").read_text())


async def source(session, event_id: str) -> dict:
    if not event_id.startswith("bs-"):
        raise ValueError("Для участков работ нужен контур гари")
    rows = (
        (
            await session.execute(
                text("""
        SELECT sc.id, sc.epsg, sc.date_post::text AS date_post,
               sc.processed_at::text AS processed_at, sc.files->>'aux' AS aux,
               json_agg(json_build_object('severity',sp.severity,
                   'geometry',ST_AsGeoJSON(sp.geom)::json)) AS polygons
        FROM scenes sc JOIN severity_polygons sp ON sp.scene_id=sc.id
        WHERE sc.kind='bs' AND sc.status='ready'
          AND coalesce(nullif(sc.fire_event_id,''),sc.id)=:key
        GROUP BY sc.id ORDER BY sc.date_post DESC, sc.id ASC
    """),
                {"key": event_id[3:]},
            )
        )
        .mappings()
        .all()
    )
    if not rows:
        raise LookupError("Контур гари не найден")
    return {"event_id": event_id, "scenes": [dict(row) for row in rows]}


def fingerprint(data: dict) -> str:
    stamps = [(s["id"], s["processed_at"], s["date_post"], s["aux"]) for s in data["scenes"]]
    return hashlib.sha256(
        json.dumps([VERSION, data["event_id"], stamps, rules()], sort_keys=True).encode()
    ).hexdigest()[:32]


def key(job: str) -> str:
    return f"work-map/v{VERSION}/{job}/report.json"


def read(job: str) -> dict | None:
    return json.loads(s3.get_bytes(key(job))) if s3.exists(key(job)) else None


def save(report: dict) -> None:
    report["updated_at"] = now()
    s3.put_bytes(key(report["id"]), json.dumps(report, allow_nan=False).encode(), "application/json")


def public(report: dict) -> dict:
    return {k: v for k, v in report.items() if k != "source"}


async def request(session, event_id: str, start: bool = False) -> dict:
    data = await source(session, event_id)
    job = fingerprint(data)
    lock, token = f"fw:work-map:create:{job}", uuid.uuid4().hex
    if not await redis.set(lock, token, nx=True, ex=30):
        return {"id": job, "event_id": event_id, "status": "queued"}
    try:
        report = await asyncio.to_thread(read, job)
        if report and report["status"] in {"running", "queued"}:
            age = (datetime.now(UTC) - datetime.fromisoformat(report["updated_at"])).total_seconds()
            if age > 600 and not await redis.exists(f"fw:work-map:worker:{job}"):
                report.update(status="error", message="Обработка прервалась. Повторите расчёт")
                await asyncio.to_thread(save, report)
        if report and (report["status"] != "error" or not start):
            return public(report)
        if not start:
            return {"id": job, "event_id": event_id, "status": "idle"}
        report = {"id": job, "event_id": event_id, "status": "queued", "source": data}
        await asyncio.to_thread(save, report)
        try:
            await broker.publish({"job_id": job}, queue=WORK_MAP_QUEUE, persist=True)
        except Exception:
            report.update(status="error", message="Очередь расчёта недоступна")
            await asyncio.to_thread(save, report)
        return public(report)
    finally:
        await unlock(lock, token)


def landcover(scene: dict, grid: dict) -> np.ndarray:
    if not scene["aux"]:
        return np.zeros((grid["height"], grid["width"]), dtype="uint8")
    with (
        MemoryFile(s3.get_bytes(scene["aux"])) as memory,
        memory.open() as src,
        WarpedVRT(
            src,
            crs=f"EPSG:{grid['epsg']}",
            transform=grid["transform"],
            width=grid["width"],
            height=grid["height"],
            resampling=Resampling.nearest,
            nodata=0,
        ) as vrt,
    ):
        return vrt.read(3)


def calculate(data: dict) -> dict:
    scene_list = sorted(data["scenes"], key=lambda s: s["id"])
    scene_list.sort(key=lambda s: s["date_post"], reverse=True)
    region = make_valid(unary_union([shape(p["geometry"]) for s in scene_list for p in s["polygons"]]))
    grid = make_grid(mapping(region), scene_list[0]["epsg"])
    to_local = Transformer.from_crs(4326, grid["epsg"], always_xy=True).transform
    to_wgs = Transformer.from_crs(grid["epsg"], 4326, always_xy=True).transform
    exact_region = make_valid(transform(to_local, region))
    prepared_region = prep(exact_region)
    size = (grid["height"], grid["width"])
    severity, cover = np.zeros(size, dtype="uint8"), np.zeros(size, dtype="uint8")
    for scene in scene_list:
        polygons = [
            (mapping(make_valid(transform(to_local, shape(p["geometry"])))), p["severity"])
            for p in scene["polygons"]
        ]
        part = rasterize(polygons, out_shape=size, transform=grid["transform"], dtype="uint8")
        take = (severity == 0) & (part > 0) & grid["mask"]
        if not take.any():
            continue
        lc = landcover(scene, grid)
        severity[take] = part[take]
        cover[take] = np.where(np.isfinite(lc[take]) & (lc[take] > 0) & (lc[take] < 255), lc[take], 0).astype(
            "uint8"
        )
    # One class encodes both severity and cover: each feature has an interpretable reason.
    classes = severity.astype("int32") * 256 + cover
    config = rules()
    features, totals = [], {}
    for geometry, value in shapes(classes, mask=severity > 0, transform=grid["transform"]):
        sev, code = divmod(int(value), 256)
        group = LC_GROUP_BY_CODE.get(code, "other") if code else "unknown"
        action = config["rules"][group][str(sev)] if group != "unknown" else "unknown"
        polygon = make_valid(shape(geometry))
        # Fast rectangle clipping limits exact intersection to the current zone;
        # repeatedly intersecting thousands of zones with the whole scar is quadratic.
        local_boundary = None
        if not prepared_region.covers(polygon):
            west, south, east, north = polygon.bounds
            try:
                local_boundary = make_valid(clip_by_rect(exact_region, west - 0.01, south - 0.01, east + 0.01, north + 0.01))
            except GEOSException:
                local_boundary = exact_region
        clipped = polygon if local_boundary is None else polygon.intersection(local_boundary)
        if clipped.is_empty or clipped.area <= 0:
            continue
        # Intersections at source boundaries may produce collections; retain only areal parts.
        if clipped.geom_type == "GeometryCollection":
            clipped = unary_union([g for g in clipped.geoms if g.geom_type in {"Polygon", "MultiPolygon"}])
        if clipped.is_empty:
            continue
        area = clipped.area / 10_000
        totals[action] = totals.get(action, 0) + area
        features.append(
            {
                "type": "Feature",
                "id": len(features) + 1,
                "properties": {
                    "id": len(features) + 1,
                    "action": action,
                    "label": LABELS[action],
                    "severity": sev,
                    "severity_label": SEVERITY_LABELS[sev],
                    "landcover": group,
                    "landcover_label": LC_GROUP_LABELS.get(group, "покров неизвестен"),
                    "area_ha": area,
                },
                "geometry": mapping(transform(to_wgs, clipped)),
            }
        )
    return {
        "status": "ready",
        "bbox": list(region.bounds),
        "area_ha": sum(totals.values()),
        "totals": [
            {"action": action, "label": LABELS[action], "area_ha": totals[action]}
            for action in LABELS
            if action in totals
        ],
        "map": {"type": "FeatureCollection", "features": features},
    }


async def process(job: str) -> None:
    lock, token = f"fw:work-map:worker:{job}", uuid.uuid4().hex
    if not await redis.set(lock, token, nx=True, ex=600):
        return
    try:
        report = await asyncio.to_thread(read, job)
        if not report or report["status"] == "ready":
            return
        report.update(status="running", message=None)
        await asyncio.to_thread(save, report)
        try:
            report.update(await asyncio.to_thread(calculate, report["source"]))
        except ValueError as exc:
            report.update(status="error", message=str(exc))
        except Exception:
            logging.getLogger(__name__).exception("Work map failed: %s", job)
            report.update(status="error", message="Не удалось прочитать данные участка. Повторите расчёт")
        await asyncio.to_thread(save, report)
    finally:
        await unlock(lock, token)
