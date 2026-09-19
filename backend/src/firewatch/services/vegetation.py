"""Same-season Sentinel-2 observations, not a forest-restoration classifier.

Durable results live in S3; RabbitMQ runs the bounded acquisition in the worker.
Only COG windows are read. Public catalog URLs are never supplied by the client.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import json
import logging
import math
import time
import uuid
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from urllib.parse import urlparse

import httpx
import numpy as np
import rasterio
from affine import Affine
from PIL import Image
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.vrt import WarpedVRT
from scipy.ndimage import binary_erosion
from shapely import make_valid
from shapely.geometry import box, mapping, shape
from shapely.ops import transform

from firewatch.config import get_settings
from firewatch.infra import s3
from firewatch.infra.cache import redis

log = logging.getLogger(__name__)
VERSION = 2
EARTH = "https://earth-search.aws.element84.com/v1/search"
PLANETARY = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
EARTH_HOST = "e84-earth-search-sentinel-data.s3.us-west-2.amazonaws.com"
PC_HOST = "sentinel2l2a01.blob.core.windows.net"
KEYS = ("red", "nir", "swir22", "scl", "visual")
QUALITY = 0.8


def now() -> str:
    return datetime.now(UTC).isoformat()


def years_for(fire_from: str, today: date | None = None) -> list[int]:
    today = today or date.today()
    last = today.year if today >= date(today.year, 7, 16) else today.year - 1
    first = max(2017, int(fire_from[:4]) - 1)
    if first > last:
        raise ValueError("Ещё нет завершённого летнего сезона для сравнения")
    return list(range(first, last + 1))


def make_grid(geometry: dict, epsg: int) -> dict:
    local = make_valid(
        transform(Transformer.from_crs(4326, epsg, always_xy=True).transform, make_valid(shape(geometry)))
    )
    if local.is_empty:
        raise ValueError("Для наблюдения нужен контур гари")
    w, s, e, n = local.bounds
    w, s, e, n = (
        math.floor(w / 20) * 20,
        math.floor(s / 20) * 20,
        math.ceil(e / 20) * 20,
        math.ceil(n / 20) * 20,
    )
    width, height = round((e - w) / 20), round((n - s) / 20)
    if width * height > 1_100_000 or max(width, height) > 1500:
        raise ValueError("Гарь слишком протяжённая: пока доступны окна до 440 км² и 30 км по стороне")
    affine = Affine(20, 0, w, 0, -20, n)
    mask = geometry_mask([mapping(local)], (height, width), affine, invert=True)
    if not mask.any():
        raise ValueError("Контур слишком мал для анализа с шагом 20 м")
    region = transform(Transformer.from_crs(epsg, 4326, always_xy=True).transform, box(w, s, e, n))
    return {
        "epsg": epsg,
        "width": width,
        "height": height,
        "transform": affine,
        "mask": mask,
        "region": region,
    }


def fingerprint(source: dict, years: list[int]) -> str:
    return hashlib.sha256(json.dumps([VERSION, source, years], sort_keys=True).encode()).hexdigest()[:32]


def key(job: str, name: str) -> str:
    return f"vegetation/v{VERSION}/{job}/{name}"


def read_report(job: str) -> dict | None:
    path = key(job, "report.json")
    return json.loads(s3.get_bytes(path)) if s3.exists(path) else None


def save_report(report: dict) -> None:
    report["updated_at"] = now()
    s3.put_bytes(
        key(report["id"], "report.json"), json.dumps(report, allow_nan=False).encode(), "application/json"
    )


def public(report: dict) -> dict:
    return {k: v for k, v in report.items() if k != "source"}


def asset_url(url: str) -> str:
    p = urlparse(url)
    if (
        p.scheme != "https"
        or p.hostname not in {EARTH_HOST, PC_HOST}
        or p.port not in (None, 443)
        or p.username
        or p.password
    ):
        raise ValueError("Unexpected satellite asset origin")
    return url


def sign_pc(client: httpx.Client, href: str) -> str:
    asset_url(href)
    r = client.get("https://planetarycomputer.microsoft.com/api/sas/v1/sign", params={"href": href})
    r.raise_for_status()
    return asset_url(r.json()["href"])


def candidates(grid: dict, year: int, provider: str = "earth") -> list[dict]:
    """Bounded candidates from one provider; acquisition controls failover."""
    settings = get_settings()
    with httpx.Client(
        timeout=settings.external_timeout_seconds, trust_env=False, follow_redirects=False
    ) as client:
        endpoint, collection = (
            (settings.stac_url.rstrip("/") + "/search", "sentinel-2-c1-l2a")
            if provider == "earth"
            else (PLANETARY, "sentinel-2-l2a")
        )
        body = {
            "collections": [collection],
            "bbox": list(grid["region"].bounds),
            "datetime": f"{year}-06-15T00:00:00Z/{year}-07-15T23:59:59Z",
            "limit": 100,
            "query": {"eo:cloud_cover": {"lt": 70}},
        }
        r = client.post(endpoint, json=body)
        r.raise_for_status()
        found = [f for f in r.json()["features"] if make_valid(shape(f["geometry"])).covers(grid["region"])]
        # Within the low-cloud group, favour the same calendar date, not tiny
        # differences in whole-tile cloud cover. Vegetation changes within a month.
        found.sort(
            key=lambda f: (
                f["properties"]["eo:cloud_cover"] >= 20,
                abs((date.fromisoformat(f["properties"]["datetime"][:10]) - date(year, 6, 30)).days),
                f["properties"]["eo:cloud_cover"],
            )
        )
        # Overlapping tiles from the same pass must not consume all three attempts.
        by_day = {}
        for item in found:
            by_day.setdefault(item["properties"]["datetime"][:10], item | {"provider": provider})
        return list(by_day.values())[:3]


def acquire_year(grid: dict, year: int) -> tuple[dict | None, dict | None, float]:
    best, best_item, best_share = None, None, -1.0
    failed = False
    for provider in ("earth", "planetary"):
        try:
            items = candidates(grid, year, provider)
        except Exception as exc:
            log.warning("Catalog %s failed for %s: %s", provider, year, type(exc).__name__)
            failed = True
            continue
        for item in items:
            try:
                frame = read_frame(grid, item)
            except Exception as exc:
                # Never log signed asset URLs from GDAL exceptions.
                log.warning("Frame %s failed: %s", item["id"], type(exc).__name__)
                failed = True
                continue
            share = float(frame["valid"].sum() / grid["mask"].sum())
            if share > best_share:
                best, best_item, best_share = frame, item, share
            if share >= 0.95:
                return best, best_item, best_share
    if best is None and failed:
        raise RuntimeError("Источник снимков временно недоступен")
    return best, best_item, best_share


def pc_coefficients(xml: bytes) -> dict[str, tuple[float, float]]:
    if len(xml) > 2_000_000:
        raise ValueError("Oversized product metadata")
    root = ET.fromstring(xml)
    quant = next(float(e.text) for e in root.iter() if e.tag.split("}")[-1] == "BOA_QUANTIFICATION_VALUE")
    if quant <= 0:
        raise ValueError("Invalid quantification value")
    offsets = {
        int(e.attrib["band_id"]): float(e.text)
        for e in root.iter()
        if e.tag.split("}")[-1] == "BOA_ADD_OFFSET"
    }
    # Sentinel band IDs are zero-based: B04=3, B08=7, B12=12 (B8A=8).
    return {k: (1 / quant, offsets.get(i, 0) / quant) for k, i in (("red", 3), ("nir", 7), ("swir22", 12))}


def prepare_assets(item: dict) -> dict:
    if item["provider"] == "earth":
        # RGB and categorical SCL do not require reflectance coefficients. Some
        # reprocessed STAC items legitimately omit raster:bands for these assets.
        return {
            k: {
                "url": asset_url(item["assets"][k]["href"]),
                "band": {} if k in ("visual", "scl") else item["assets"][k]["raster:bands"][0],
            }
            for k in KEYS
        }
    with httpx.Client(
        timeout=get_settings().external_timeout_seconds, trust_env=False, follow_redirects=False
    ) as client:
        r = client.get(sign_pc(client, item["assets"]["product-metadata"]["href"]))
        r.raise_for_status()
        coeff = pc_coefficients(r.content)
        assets = {}
        for k, native in zip(KEYS, ("B04", "B08", "B12", "SCL", "visual"), strict=True):
            scale, offset = coeff.get(k, (1, 0))
            assets[k] = {
                "url": sign_pc(client, item["assets"][native]["href"]),
                "band": {"scale": scale, "offset": offset, "nodata": 0},
            }
        return assets


def reflectance(raw: np.ndarray, metadata: dict) -> np.ndarray:
    result = raw.astype("float32") * metadata["scale"] + metadata.get("offset", 0)
    result[raw == metadata.get("nodata", 0)] = np.nan
    return result


def read_frame(grid: dict, item: dict) -> dict:
    assets = prepare_assets(item)

    def read(k):
        with (
            rasterio.Env(
                GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
                GDAL_HTTP_TIMEOUT="25",
                GDAL_HTTP_CONNECTTIMEOUT="10",
                GDAL_HTTP_MAX_RETRY="1",
                GDAL_CACHEMAX=32_000_000,
            ),
            rasterio.open(assets[k]["url"]) as src,
            WarpedVRT(
                src,
                crs=f"EPSG:{grid['epsg']}",
                transform=grid["transform"],
                width=grid["width"],
                height=grid["height"],
                resampling=Resampling.nearest if k == "scl" else Resampling.average,
            ) as vrt,
        ):
            raw = vrt.read([1, 2, 3]) if k == "visual" else vrt.read(1)
        return k, raw if k in ("visual", "scl") else reflectance(raw, assets[k]["band"])

    with ThreadPoolExecutor(max_workers=3) as pool:
        arrays = dict(pool.map(read, KEYS))
    valid = grid["mask"] & np.isin(arrays["scl"], [4, 5])
    valid &= np.isfinite(arrays["red"]) & np.isfinite(arrays["nir"]) & np.isfinite(arrays["swir22"])
    valid &= (arrays["nir"] + arrays["red"] > 0.02) & (arrays["nir"] + arrays["swir22"] > 0.02)
    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi = np.where(valid, (arrays["nir"] - arrays["red"]) / (arrays["nir"] + arrays["red"]), np.nan)
        nbr = np.where(valid, (arrays["nir"] - arrays["swir22"]) / (arrays["nir"] + arrays["swir22"]), np.nan)
    return {"ndvi": ndvi, "nbr": nbr, "valid": valid, "rgb": np.moveaxis(arrays["visual"], 0, -1)}


def webp(rgb: np.ndarray) -> bytes:
    out = io.BytesIO()
    Image.fromarray(np.asarray(rgb, dtype=np.uint8)).save(out, format="WEBP", quality=88)
    return out.getvalue()


def decorate(rgb: np.ndarray, mask: np.ndarray, valid: np.ndarray) -> np.ndarray:
    result = rgb.astype("float32").copy()
    result[~mask] *= 0.45
    yy, xx = np.indices(mask.shape)
    unknown = mask & ~valid
    result[unknown] = np.where((((xx + yy) % 8) < 4)[unknown, None], [106, 106, 106], [67, 67, 67])
    result[mask & ~binary_erosion(mask)] = [248, 240, 219]
    return result.astype("uint8")


def compare(base: dict, frame: dict, mask: np.ndarray) -> tuple[dict, np.ndarray]:
    common = mask & base["valid"] & frame["valid"]
    share = float(common.sum() / mask.sum())
    delta = frame["ndvi"] - base["ndvi"]
    # Display range is not an ecological threshold. All metrics use the same pixels.
    t = np.clip(np.nan_to_num(delta) / 0.3, -1, 1)[..., None]
    neutral = np.array([220, 213, 192])
    color = np.where(
        t < 0,
        neutral + (-t) * (np.array([163, 94, 50]) - neutral),
        neutral + t * (np.array([49, 124, 93]) - neutral),
    )
    rgb = frame["rgb"].copy()
    rgb[common] = color[common].astype("uint8")
    sufficient = share >= QUALITY
    return {
        "common_share": share,
        "compared_ha": round(float(common.sum()) * 0.04, 2),
        "delta_ndvi": round(float(np.median(delta[common])), 3) if sufficient else None,
        "baseline_ndvi": round(float(np.median(base["ndvi"][common])), 3) if sufficient else None,
        "current_ndvi": round(float(np.median(frame["ndvi"][common])), 3) if sufficient else None,
    }, decorate(rgb, mask, common)


def save_frame(job: str, year: int, frame: dict, grid: dict) -> None:
    out = io.BytesIO()
    np.savez_compressed(out, **frame)
    s3.put_bytes(key(job, f"{year}.npz"), out.getvalue(), "application/octet-stream")
    s3.put_bytes(
        key(job, f"{year}-rgb.webp"), webp(decorate(frame["rgb"], grid["mask"], frame["valid"])), "image/webp"
    )


def load_frame(job: str, year: int) -> dict:
    with np.load(io.BytesIO(s3.get_bytes(key(job, f"{year}.npz"))), allow_pickle=False) as data:
        return {k: data[k] for k in data.files}


async def unlock(name: str, token: str) -> None:
    await redis.eval(
        "if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end",
        1,
        name,
        token,
    )


async def process(job: str) -> None:
    lock, token = f"fw:vegetation:worker:{job}", uuid.uuid4().hex
    if not await redis.set(lock, token, nx=True, ex=180):
        return

    async def heartbeat():
        while True:
            await asyncio.sleep(30)
            renewed = await redis.eval(
                "if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('expire',KEYS[1],180) else return 0 end",
                1,
                lock,
                token,
            )
            if not renewed:
                raise RuntimeError("Vegetation worker lease lost")

    heartbeat_task = asyncio.create_task(heartbeat())
    report = None
    try:
        report = await asyncio.to_thread(read_report, job)
        if report is None or report["status"] == "ready":
            return
        source = report["source"]
        grid = await asyncio.to_thread(make_grid, source["geometry"], source["epsg"])
        report["status"] = "running"
        # Newest first; the pre-fire reference next. A closed tab does not cancel work.
        years = report["years"]
        order = list(dict.fromkeys([years[-1], years[0], *reversed(years[1:-1])]))
        for year in order:
            if heartbeat_task.done():
                await heartbeat_task
            existing = next((f for f in report["frames"] if f["year"] == year), None)
            if existing and existing["status"] in {"ready", "cloudy"}:
                continue
            report["active_year"] = year
            await asyncio.to_thread(save_report, report)
            started = time.perf_counter()
            entry = {"year": year, "status": "missing", "message": "Нет снимка с полным покрытием участка"}
            try:
                best, best_item, best_share = await asyncio.to_thread(acquire_year, grid, year)
                if heartbeat_task.done():
                    await heartbeat_task
                if best is not None:
                    await asyncio.to_thread(save_frame, job, year, best, grid)
                    observed = best_item["properties"]["datetime"][:10]
                    role = (
                        "before"
                        if observed < source["date_from"]
                        else "after"
                        if observed > source["date_to"]
                        else "during"
                    )
                    entry = {
                        "year": year,
                        "status": "ready" if best_share >= QUALITY else "cloudy",
                        "date": observed,
                        "role": role,
                        "valid_share": best_share,
                        "item_id": best_item["id"],
                        "provider": best_item["provider"],
                        "seconds": round(time.perf_counter() - started, 2),
                        "rgb_url": f"/api/v1/vegetation/{job}/{year}/rgb.webp",
                    }
            except Exception:
                log.exception("Vegetation year failed: %s %s", job, year)
                entry = {"year": year, "status": "error", "message": "Источник снимков временно недоступен"}
            report["frames"] = sorted(
                [f for f in report["frames"] if f["year"] != year] + [entry], key=lambda f: f["year"]
            )
            # Calculate only against an actual pre-fire frame and common clear pixels.
            base_entry = next(
                (
                    f
                    for f in report["frames"]
                    if f["year"] == years[0] and f.get("role") == "before" and f["status"] == "ready"
                ),
                None,
            )
            if base_entry:
                base = await asyncio.to_thread(load_frame, job, years[0])
                for f in report["frames"]:
                    if f["status"] not in {"ready", "cloudy"} or f["year"] == years[0] or "comparison" in f:
                        continue
                    frame = await asyncio.to_thread(load_frame, job, f["year"])
                    stats, rgb = await asyncio.to_thread(compare, base, frame, grid["mask"])
                    gap = abs(
                        (
                            date.fromisoformat(f["date"]).replace(year=2000)
                            - date.fromisoformat(base_entry["date"]).replace(year=2000)
                        ).days
                    )
                    stats["season_gap_days"] = gap
                    if gap > 14:
                        stats.update(delta_ndvi=None, baseline_ndvi=None, current_ndvi=None)
                    await asyncio.to_thread(
                        s3.put_bytes, key(job, f"{f['year']}-change.webp"), webp(rgb), "image/webp"
                    )
                    f["comparison"] = stats | {"baseline_date": base_entry["date"]}
                    f["change_url"] = f"/api/v1/vegetation/{job}/{f['year']}/change.webp"
            await asyncio.to_thread(save_report, report)
        report["active_year"] = None
        report["status"] = (
            "partial"
            if any(f["status"] in {"error", "missing", "cloudy"} for f in report["frames"])
            else "ready"
        )
        await asyncio.to_thread(save_report, report)
    except Exception:
        log.exception("Vegetation job failed: %s", job)
        if report:
            report.update(
                status="error",
                active_year=None,
                message="Не удалось завершить наблюдения. Повторите загрузку",
            )
            await asyncio.to_thread(save_report, report)
    finally:
        heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await heartbeat_task
        await unlock(lock, token)
