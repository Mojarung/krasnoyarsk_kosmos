"""Сборка BS-чипа по произвольной области из открытых данных: тот же формат, что у чипов кейса.

Sentinel-2 L2A, рельеф Copernicus GLO-30 и покров ESA WorldCover читаются окнами из облачных GeoTIFF
и приводятся к сетке 20 м в UTM. Радар в открытом доступе без авторизации и калибровки не получить,
поэтому каналы Sentinel-1 заполняются нейтральной константой: разность «после - до» равна нулю,
и модель опирается на оптику.
"""

from __future__ import annotations

import logging
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from affine import Affine
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.errors import RasterioIOError
from rasterio.features import geometry_mask
from rasterio.vrt import WarpedVRT
from rasterio.windows import from_bounds
from scipy import ndimage
from shapely.geometry import Polygon, box, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform

from fire_ml.bs_features import SCL_INVALID
from fire_ml.contract import BS_AUX_BANDS, BS_S1_BANDS, BS_S2_BANDS
from firewatch.infra import stac

log = logging.getLogger(__name__)

CHIP_PX = 512
GSD_M = 20.0
CHIP_M = CHIP_PX * GSD_M
# Квадрат чипа, заданный в градусах, в UTM чуть повёрнут и выступает за 10,24 км на доли процента.
CHIP_OVERHANG = 0.05
WGS84 = 4326
S2_ASSETS = ("blue", "green", "red", "rededge1", "rededge2", "rededge3", "nir08", "swir16", "swir22", "scl")
S2_FINE_ASSETS = frozenset({"blue", "green", "red"})
SCL_NODATA = 0
# Медианы обратного рассеяния по обучающим чипам кейса, дБ x 100.
S1_NEUTRAL = {"VV": -1200, "VH": -1900}
WORLDCOVER_URL = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"
WORLDCOVER_TILE_DEG = 3
DEM_NODATA = -32768.0
READ_THREADS = 8
READ_ATTEMPTS = 3
SLOPE_SMOOTH_PX = 3
GDAL_HTTP = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.TIF",
    "GDAL_HTTP_TIMEOUT": "300",
    "GDAL_HTTP_MAX_RETRY": "3",
    "GDAL_HTTP_RETRY_DELAY": "2",
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "CPL_VSIL_CURL_CHUNK_SIZE": "1048576",
    "VSI_CACHE": "TRUE",
    "AWS_NO_SIGN_REQUEST": "YES",
}


@dataclass(frozen=True)
class ChipGrid:
    epsg: int
    transform: Affine
    width: int = CHIP_PX
    height: int = CHIP_PX

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        west, north = self.transform @ (0, 0)
        east, south = self.transform @ (self.width, self.height)
        return west, south, east, north

    def footprint_wgs84(self) -> Polygon:
        to_wgs84 = Transformer.from_crs(self.epsg, WGS84, always_xy=True).transform
        return shapely_transform(to_wgs84, box(*self.bounds))


@dataclass(frozen=True)
class AcquiredChip:
    paths: dict[str, Path]
    date_pre: date
    date_post: date
    cloud_frac: float
    valid_frac: float
    provenance: dict[str, Any]


def utm_epsg(lon: float, lat: float) -> int:
    zone = int((lon + 180.0) // 6.0) + 1
    return (32600 if lat >= 0 else 32700) + zone


class AreaTooLargeError(ValueError):
    pass


def plan_grids(area: BaseGeometry, max_chips: int) -> list[ChipGrid]:
    """Покрывает область чипами 512x512 по 20 м вокруг её центра.

    Область, которая не влезает в max_chips чипов, отклоняется: молча обрезать её до центра значило бы
    выдать справку не по той территории, которую просили.
    """
    center = area.centroid
    epsg = utm_epsg(center.x, center.y)
    to_utm = Transformer.from_crs(WGS84, epsg, always_xy=True).transform
    west, south, east, north = shapely_transform(to_utm, area).bounds
    columns = max(1, math.ceil((east - west) / CHIP_M - CHIP_OVERHANG))
    rows = max(1, math.ceil((north - south) / CHIP_M - CHIP_OVERHANG))
    if columns * rows > max_chips:
        side = CHIP_M / 1000.0
        raise AreaTooLargeError(
            f"Область {(east - west) / 1000:.0f} x {(north - south) / 1000:.0f} км не помещается в {max_chips} чипа "
            f"по {side:.2f} x {side:.2f} км. Выберите область меньше"
        )

    origin_x = round(((west + east) / 2.0 - columns * CHIP_M / 2.0) / GSD_M) * GSD_M
    origin_y = round(((south + north) / 2.0 + rows * CHIP_M / 2.0) / GSD_M) * GSD_M
    return [
        ChipGrid(
            epsg=epsg,
            transform=Affine(GSD_M, 0.0, origin_x + col * CHIP_M, 0.0, -GSD_M, origin_y - row * CHIP_M),
        )
        for row in range(rows)
        for col in range(columns)
    ]


def snap_to_blocks(grid: ChipGrid, item: stac.S2Item) -> ChipGrid:
    """Сдвигает чип на решётку внутренних блоков COG. Блок 20-метрового канала - те же 512 px,
    так что выровненный чип читается одним блоком на канал вместо четырёх."""
    if item.origin is None or item.epsg != grid.epsg:
        return grid
    west, north = grid.transform @ (0, 0)
    origin_x, origin_y = item.origin
    snapped_x = origin_x + round((west - origin_x) / CHIP_M) * CHIP_M
    snapped_y = origin_y + round((north - origin_y) / CHIP_M) * CHIP_M
    return ChipGrid(epsg=grid.epsg, transform=Affine(GSD_M, 0.0, snapped_x, 0.0, -GSD_M, snapped_y))


def _read(href: str, grid: ChipGrid, resampling: Resampling, nodata: float | None = None) -> np.ndarray:
    """На медленном канале ответ S3 иногда обрывается посреди блока, поэтому чтение повторяется."""
    for attempt in range(1, READ_ATTEMPTS + 1):
        try:
            return _read_once(href, grid, resampling, nodata)
        except RasterioIOError:
            if attempt == READ_ATTEMPTS:
                raise
            log.warning("Обрыв чтения %s, попытка %d из %d", href, attempt, READ_ATTEMPTS)
    raise AssertionError("unreachable")


def _read_once(href: str, grid: ChipGrid, resampling: Resampling, nodata: float | None) -> np.ndarray:
    with rasterio.Env(**GDAL_HTTP), rasterio.open(href) as source:
        if source.crs is not None and source.crs.to_epsg() == grid.epsg:
            # Та же проекция: читаем окно напрямую. out_shape заставляет GDAL взять обзорный уровень,
            # и 10-метровый канал приходит уже усреднённым до 20 м.
            return source.read(
                1,
                window=from_bounds(*grid.bounds, transform=source.transform),
                out_shape=(grid.height, grid.width),
                resampling=resampling,
                boundless=True,
                fill_value=0 if nodata is None else nodata,
            )
        options = {} if nodata is None else {"src_nodata": nodata, "nodata": nodata}
        with WarpedVRT(
            source,
            crs=f"EPSG:{grid.epsg}",
            transform=grid.transform,
            width=grid.width,
            height=grid.height,
            resampling=resampling,
            **options,
        ) as vrt:
            return vrt.read(1)


def read_scl(item: stac.S2Item, grid: ChipGrid) -> np.ndarray:
    return _read(item.assets["scl"], grid, Resampling.nearest, SCL_NODATA).astype(np.uint16)


def invalid_share(scl: np.ndarray) -> float:
    return float(np.isin(scl, SCL_INVALID).mean())


def read_band(item: stac.S2Item, asset: str, grid: ChipGrid) -> np.ndarray:
    resampling = Resampling.average if asset in S2_FINE_ASSETS else Resampling.nearest
    values = _read(item.assets[asset], grid, resampling, 0).astype(np.int32)
    return np.where(values > 0, np.clip(values - item.boa_offset, 1, None), 0)


def slope_degrees(dem: np.ndarray, gsd: float) -> np.ndarray:
    # Исходный рельеф 30 м. После пересчёта на 20 м остаётся рябь, которая завышает уклон на равнине.
    smooth = ndimage.uniform_filter(dem.astype(np.float32), SLOPE_SMOOTH_PX, mode="nearest")
    d_row, d_col = np.gradient(smooth, gsd)
    return np.degrees(np.arctan(np.hypot(d_row, d_col)))


def worldcover_tiles(bounds_wgs84: tuple[float, float, float, float]) -> list[str]:
    west, south, east, north = bounds_wgs84
    step = WORLDCOVER_TILE_DEG
    tiles = []
    for lat in range(math.floor(south / step) * step, math.floor(north / step) * step + 1, step):
        for lon in range(math.floor(west / step) * step, math.floor(east / step) * step + 1, step):
            name = f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}{'E' if lon >= 0 else 'W'}{abs(lon):03d}"
            tiles.append(WORLDCOVER_URL.format(tile=name))
    return tiles


def _mosaic(hrefs: list[str], grid: ChipGrid, resampling: Resampling, nodata: float) -> np.ndarray:
    result = np.full((grid.height, grid.width), nodata, dtype=np.float32)
    for href in hrefs:
        part = _read(href, grid, resampling, nodata).astype(np.float32)
        result = np.where(result == nodata, part, result)
    return result


def read_aux(grid: ChipGrid) -> np.ndarray:
    footprint = grid.footprint_wgs84()
    dem = _mosaic(stac.search_dem(footprint), grid, Resampling.bilinear, DEM_NODATA)
    dem = np.where(dem == DEM_NODATA, 0.0, dem)
    landcover = _mosaic(worldcover_tiles(footprint.bounds), grid, Resampling.mode, 0.0)
    return np.stack([np.rint(dem), np.rint(slope_degrees(dem, GSD_M)), landcover]).astype(np.int16)


def write_geotiff(path: Path, data: np.ndarray, grid: ChipGrid, names: tuple[str, ...]) -> Path:
    profile = {
        "driver": "GTiff",
        "width": grid.width,
        "height": grid.height,
        "count": data.shape[0],
        "dtype": data.dtype.name,
        "crs": f"EPSG:{grid.epsg}",
        "transform": grid.transform,
        "compress": "deflate",
    }
    with rasterio.open(path, "w", **profile) as target:
        target.write(data)
        target.descriptions = names
    return path


def pick_item(
    grid: ChipGrid,
    target: date,
    days: int,
    candidates: int,
    tile: str | None = None,
    *,
    before: date | None = None,
    after: date | None = None,
    mask: np.ndarray | None = None,
) -> tuple[stac.S2Item, np.ndarray]:
    """Облачность в каталоге указана на весь тайл 110 км, поэтому у лучших кандидатов маска SCL читается по самому чипу."""
    footprint = grid.footprint_wgs84()
    items = [
        item
        for item in stac.search_s2(footprint, target, days)
        if (before is None or item.acquired.date() < before)
        and (after is None or item.acquired.date() > after)
    ]
    ranked = stac.rank_items(items, footprint, target, grid.epsg, tile)
    if not ranked:
        raise stac.NoImageryError(f"В каталоге нет сцен Sentinel-2 на {target:%d.%m.%Y} ± {days} дн.")
    with ThreadPoolExecutor(candidates) as pool:
        masks = list(pool.map(lambda item: read_scl(item, grid), ranked[:candidates]))
    scored = zip(ranked, masks, strict=False)
    return min(
        scored,
        key=lambda pair: (
            round(invalid_share(pair[1] if mask is None else pair[1][mask]), 2),
            abs((pair[0].acquired.date() - target).days),
        ),
    )


def assemble_chip(
    grid: ChipGrid,
    date_pre: date,
    date_post: date,
    folder: Path,
    *,
    days: int,
    candidates: int,
    fire_context: dict | None = None,
) -> tuple[ChipGrid, AcquiredChip]:
    """Возвращает и сетку: она сдвигается на решётку блоков тайла, в котором нашёлся снимок «после»."""
    if fire_context:
        # Keep the requested footprint: COG block snapping can move the hotspot out of the chip.
        to_utm = Transformer.from_crs(4326, grid.epsg, always_xy=True).transform
        target = shapely_transform(to_utm, shape(fire_context["target_geometry"]))
        mask = geometry_mask([mapping(target)], (grid.height, grid.width), grid.transform, invert=True)
        if not mask.any():
            raise stac.NoImageryError("Термоточки не попали в область снимка")
        post, scl_post = pick_item(
            grid, date_post, days, candidates, after=date.fromisoformat(fire_context["fire_end"]), mask=mask
        )
        pre, scl_pre = pick_item(
            grid,
            date_pre,
            days,
            candidates,
            post.tile,
            before=date.fromisoformat(fire_context["fire_start"]),
            mask=mask,
        )
        valid = ~(np.isin(scl_pre, SCL_INVALID) | np.isin(scl_post, SCL_INVALID))
        if float(valid[mask].mean()) < 0.8:
            raise stac.NoImageryError(
                "Недостаточно ясных снимков у термоточек: облака, тени или пропуски данных"
            )
    else:
        post, _ = pick_item(grid, date_post, days, 1)
        grid = snap_to_blocks(grid, post)
        post, scl_post = pick_item(grid, date_post, days, candidates, post.tile)
        pre, scl_pre = pick_item(grid, date_pre, days, candidates, post.tile)
    if pre.acquired >= post.acquired:
        raise stac.NoImageryError("Снимок «до» получился не раньше снимка «после»: разнесите даты сильнее")

    optical = S2_ASSETS[:-1]
    with ThreadPoolExecutor(READ_THREADS) as pool:
        aux = pool.submit(read_aux, grid)
        bands = {
            (item.id, asset): pool.submit(read_band, item, asset, grid)
            for item in (pre, post)
            for asset in optical
        }
        s2_pre = np.stack([*(bands[(pre.id, a)].result() for a in optical), scl_pre]).astype(np.uint16)
        s2_post = np.stack([*(bands[(post.id, a)].result() for a in optical), scl_post]).astype(np.uint16)
        aux_layers = aux.result()

    neutral = np.stack(
        [np.full((grid.height, grid.width), S1_NEUTRAL[name], np.int16) for name in BS_S1_BANDS]
    )
    paths = {
        "s2_pre": write_geotiff(folder / "s2_pre.tif", s2_pre, grid, BS_S2_BANDS),
        "s2_post": write_geotiff(folder / "s2_post.tif", s2_post, grid, BS_S2_BANDS),
        "s1_pre": write_geotiff(folder / "s1_pre.tif", neutral, grid, BS_S1_BANDS),
        "s1_post": write_geotiff(folder / "s1_post.tif", neutral, grid, BS_S1_BANDS),
        "aux": write_geotiff(folder / "aux.tif", aux_layers, grid, BS_AUX_BANDS),
    }
    invalid = np.isin(scl_pre, SCL_INVALID) | np.isin(scl_post, SCL_INVALID)
    missing = (scl_pre == SCL_NODATA) | (scl_post == SCL_NODATA)
    chip = AcquiredChip(
        paths=paths,
        date_pre=pre.acquired.date(),
        date_post=post.acquired.date(),
        cloud_frac=float((invalid & ~missing).mean()),
        valid_frac=float(1.0 - invalid.mean()),
        provenance={
            "source": "Earth Search, Sentinel-2 L2A",
            "s2_pre": pre.id,
            "s2_post": post.id,
            "requested": [date_pre.isoformat(), date_post.isoformat()],
            "s1": "нейтральная константа, радар не запрашивался",
        },
    )
    return grid, chip
