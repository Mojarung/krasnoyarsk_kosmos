"""Reproducible, bounded Sentinel-2 feasibility experiment (not a production service).

Run in the API runtime, with outbound HTTPS, e.g. --out /tmp/recovery-probe.
Never downloads full tiles: an allowlisted loopback Range proxy counts actual bytes.
Outputs are experiment artifacts, not mutations of the application's database.
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import json
import math
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
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
from shapely import make_valid
from shapely.geometry import box, mapping, shape
from shapely.ops import transform, unary_union

STAC = "https://earth-search.aws.element84.com/v1"
COLLECTION = "sentinel-2-c1-l2a"
ASSETS = ("red", "nir", "swir22", "scl", "visual")
HOST = "e84-earth-search-sentinel-data.s3.us-west-2.amazonaws.com"


class RangeProxy:
    def __init__(self):
        self.urls = {}
        self.records = []
        self.lock = threading.Lock()
        self.client = httpx.Client(timeout=35, follow_redirects=False, trust_env=False)
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_HEAD(self):
                self.forward(head=True)

            def do_GET(self):
                self.forward(head=False)

            def forward(self, head):
                url = owner.urls.get(self.path)
                if not url or (not head and not self.headers.get("Range")):
                    self.send_error(400)
                    return
                started = time.perf_counter()
                try:
                    headers = {"Range": self.headers["Range"]} if not head else {}
                    with owner.client.stream("HEAD" if head else "GET", url, headers=headers) as response:
                        if not head and (
                            response.status_code != 206
                            or int(response.headers.get("content-length", 0)) > 20_000_000
                        ):
                            raise RuntimeError(
                                f"Refusing non-range/oversized response: {response.status_code}"
                            )
                        data = b"" if head else response.read()
                        self.send_response(response.status_code)
                        for key in ("Content-Length", "Content-Range", "Accept-Ranges", "Content-Type"):
                            if key in response.headers:
                                self.send_header(key, response.headers[key])
                        self.end_headers()
                        if data:
                            self.wfile.write(data)
                        record = {
                            "path": self.path,
                            "status": response.status_code,
                            "bytes": len(data),
                            "seconds": time.perf_counter() - started,
                            "range": headers.get("Range"),
                        }
                except Exception as exc:
                    record = {
                        "path": self.path,
                        "error": str(exc),
                        "bytes": 0,
                        "seconds": time.perf_counter() - started,
                    }
                    self.send_error(502)
                with owner.lock:
                    owner.records.append(record)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def register(self, href, tag):
        parsed = urlparse(href)
        if parsed.scheme != "https" or parsed.hostname != HOST:
            raise ValueError(f"Unapproved asset origin {parsed.hostname}")
        key = f"/{tag}.tif"
        self.urls[key] = href
        return f"http://127.0.0.1:{self.server.server_port}{key}"

    def close(self):
        self.server.shutdown()
        self.client.close()


def fetch_json(url, **kwargs):
    with httpx.Client(timeout=45, trust_env=False) as client:
        response = client.post(url, json=kwargs["body"]) if "body" in kwargs else client.get(url)
        response.raise_for_status()
        return response.json()


def make_case(event, name, side_km=None):
    burned = unary_union(
        [
            make_valid(shape(f["geometry"]))
            for f in event["map"]["features"]
            if f["properties"].get("kind") == "burn"
        ]
    )
    epsg = int(event["burn"]["area_crs"].split(":")[-1])
    forward = Transformer.from_crs(4326, epsg, always_xy=True).transform
    reverse = Transformer.from_crs(epsg, 4326, always_xy=True).transform
    local_burn = make_valid(transform(forward, burned))
    if side_km:
        p = (
            max(local_burn.geoms, key=lambda g: g.area).representative_point()
            if hasattr(local_burn, "geoms")
            else local_burn.representative_point()
        )
        delta = side_km * 500
        extent = box(p.x - delta, p.y - delta, p.x + delta, p.y + delta)
    else:
        extent = local_burn.envelope
    west, south, east, north = extent.bounds
    resolution = 20
    west, south = math.floor(west / resolution) * resolution, math.floor(south / resolution) * resolution
    east, north = math.ceil(east / resolution) * resolution, math.ceil(north / resolution) * resolution
    width, height = round((east - west) / resolution), round((north - south) / resolution)
    if width * height > 1_100_000:
        raise ValueError("Experiment grid exceeds one million pixels")
    transform_ = Affine(resolution, 0, west, 0, -resolution, north)
    study_burn = local_burn.intersection(extent)
    mask = geometry_mask([mapping(study_burn)], (height, width), transform_, invert=True)
    region = transform(reverse, box(west, south, east, north))
    return {
        "name": name,
        "event_id": event["id"],
        "fire_year": int(event["date_to"][:4]),
        "region": region,
        "mask": mask,
        "epsg": epsg,
        "transform": transform_,
        "width": width,
        "height": height,
        "window_km2": width * height * resolution**2 / 1e6,
        "burn_ha": int(mask.sum()) * resolution**2 / 1e4,
        "event_burn_ha": event["burn"]["area_ha"],
    }


def search(case, year):
    started = time.perf_counter()
    body = {
        "collections": [COLLECTION],
        "bbox": list(case["region"].bounds),
        "datetime": f"{year}-06-01T00:00:00Z/{year}-07-15T23:59:59Z",
        "limit": 100,
        "query": {"eo:cloud_cover": {"lt": 60}},
    }
    response = fetch_json(STAC + "/search", body=body)
    candidates = response["features"]
    complete = not any(link.get("rel") == "next" for link in response.get("links", []))
    covering = [
        f
        for f in candidates
        if shape(f["geometry"]).intersection(case["region"]).area / case["region"].area > 0.995
    ]
    covering.sort(
        key=lambda f: (
            f["properties"].get("eo:cloud_cover", 100),
            abs(int(f["properties"]["datetime"][8:10]) - 20),
        )
    )
    return {
        "case": case["name"],
        "year": year,
        "seconds": time.perf_counter() - started,
        "matched": response.get("numberMatched", len(candidates)),
        "page_complete": complete,
        "covering_candidates": len(covering),
        "items": covering[:3],
        "searched_bbox": list(case["region"].bounds),
    }


def read_asset(proxy, case, item, key, tag):
    asset = item["assets"][key]
    url = proxy.register(asset["href"], tag + "-" + key)
    started = time.perf_counter()
    with (
        rasterio.Env(
            GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
            CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
            GDAL_HTTP_TIMEOUT="40",
            GDAL_HTTP_MAX_RETRY="0",
            GDAL_CACHEMAX=32_000_000,
        ),
        rasterio.open(url) as source,
        WarpedVRT(
            source,
            crs=f"EPSG:{case['epsg']}",
            transform=case["transform"],
            width=case["width"],
            height=case["height"],
            resampling=Resampling.nearest if key == "scl" else Resampling.average,
        ) as vrt,
    ):
        array = vrt.read() if key == "visual" else vrt.read(1)
    if key not in ("scl", "visual"):
        band = asset["raster:bands"][0]
        nodata = array == band.get("nodata", 0)
        array = array.astype("float32") * band["scale"] + band.get("offset", 0)
        array[nodata] = np.nan
    return key, array, time.perf_counter() - started


def observe(proxy, case, item, out, tag):
    started = time.perf_counter()
    record_start = len(proxy.records)
    with futures.ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda key: read_asset(proxy, case, item, key, tag), ASSETS))
    arrays = {key: array for key, array, _ in results}
    # Conservative land-only cloud mask; uncertain class 7 is not silently accepted.
    valid = case["mask"] & np.isin(arrays["scl"], [4, 5])
    valid &= np.isfinite(arrays["red"]) & np.isfinite(arrays["nir"]) & np.isfinite(arrays["swir22"])
    valid &= (arrays["nir"] + arrays["red"] > 0.02) & (arrays["nir"] + arrays["swir22"] > 0.02)
    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi = np.where(valid, (arrays["nir"] - arrays["red"]) / (arrays["nir"] + arrays["red"]), np.nan)
        nbr = np.where(valid, (arrays["nir"] - arrays["swir22"]) / (arrays["nir"] + arrays["swir22"]), np.nan)
    cache = out / (tag + ".npz")
    np.savez_compressed(cache, ndvi=ndvi, nbr=nbr, valid=valid, mask=case["mask"], rgb=arrays["visual"])
    Image.fromarray(np.moveaxis(arrays["visual"], 0, -1)).save(out / (tag + ".webp"), quality=85)
    cold = time.perf_counter() - started
    start = time.perf_counter()
    with np.load(cache) as loaded:
        warm_median = float(np.nanmedian(loaded["ndvi"])) if valid.any() else None
    warm = time.perf_counter() - start
    network = proxy.records[record_start:]
    result = {
        "case": case["name"],
        "tag": tag,
        "item": item["id"],
        "date": item["properties"]["datetime"],
        "tile_cloud_pct": item["properties"]["eo:cloud_cover"],
        "cold_seconds": cold,
        "local_cache_seconds": warm,
        "download_bytes": sum(r["bytes"] for r in network),
        "http_requests": len(network),
        "http_statuses": sorted(set(r.get("status", 0) for r in network)),
        "full_asset_bytes_not_downloaded": sum(item["assets"][k]["file:size"] for k in ASSETS),
        "band_seconds": {key: sec for key, _, sec in results},
        "valid_burn_share": float(valid.sum() / case["mask"].sum()),
        "ndvi_median": warm_median,
        "nbr_median": float(np.nanmedian(nbr)) if valid.any() else None,
        "cache_bytes": cache.stat().st_size,
        "reflectance_metadata": {k: item["assets"][k]["raster:bands"] for k in ("red", "nir", "swir22")},
    }
    print(json.dumps(result), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--catalog-only", action="store_true")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    events = {
        i: fetch_json("http://localhost:8000/api/v1/events/" + i)
        for i in ("bs-FE06923", "bs-FE08918", "bs-FE04217")
    }
    cases = [
        make_case(events["bs-FE06923"], "small-1km", 1),
        make_case(events["bs-FE08918"], "volgograd-fire"),
        make_case(events["bs-FE04217"], "astrakhan-fire"),
        make_case(events["bs-FE08918"], "large-20km", 20),
    ]
    report = {
        "measured_at": datetime.now(UTC).isoformat(),
        "provider": STAC,
        "collection": COLLECTION,
        "cases": [
            {k: v for k, v in case.items() if k not in ("mask", "region", "transform")} for case in cases
        ],
        "catalog": [],
        "observations": [],
        "errors": [],
    }

    def save():
        (args.out / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    with futures.ThreadPoolExecutor(max_workers=3) as pool:
        tasks = {
            (case["name"], year): pool.submit(search, case, year)
            for case in cases
            for year in (2019, 2020, 2021, 2022, 2024, 2025, 2026)
        }
        for (name, year), task in tasks.items():
            try:
                found = task.result()
                report["catalog"].append(found)
                print(json.dumps({k: v for k, v in found.items() if k != "items"}), flush=True)
            except Exception as exc:
                report["errors"].append({"stage": "catalog", "case": name, "year": year, "error": str(exc)})
    save()
    if args.catalog_only:
        return
    proxy = RangeProxy()
    try:
        # Four spatial scales + a same-season time series on the full Volgograd fire.
        for case in cases:
            years = (
                (2019, 2020, 2021, 2022, 2024, 2025, 2026) if case["name"] == "volgograd-fire" else (2025,)
            )
            for year in years:
                found = next(
                    (r for r in report["catalog"] if r["case"] == case["name"] and r["year"] == year), None
                )
                if not found or not found["items"]:
                    report["errors"].append(
                        {
                            "case": case["name"],
                            "year": year,
                            "error": "No single tile covers the window; requires mosaicking or no imagery",
                        }
                    )
                    save()
                    continue
                try:
                    result = observe(proxy, case, found["items"][0], args.out, f"{case['name']}-{year}")
                    report["observations"].append(result)
                except Exception as exc:
                    report["errors"].append(
                        {"stage": "read", "case": case["name"], "year": year, "error": str(exc)}
                    )
                    print(f"READ ERROR {case['name']} {year}: {exc}", flush=True)
                save()
        (args.out / "http-ranges.json").write_text(json.dumps(proxy.records, indent=2), encoding="utf-8")
    finally:
        proxy.close()
    save()


if __name__ == "__main__":
    main()
