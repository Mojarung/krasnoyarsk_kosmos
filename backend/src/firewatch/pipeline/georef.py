from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine
from pyproj import Transformer
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform

WGS84 = 4326


class MissingGeoreferenceError(ValueError):
    pass


@lru_cache(maxsize=8)
def _to_wgs84(epsg: int) -> Transformer:
    return Transformer.from_crs(epsg, WGS84, always_xy=True)


@dataclass(frozen=True)
class GeoRef:
    epsg: int
    transform: Affine
    width: int
    height: int

    @classmethod
    def from_raster(cls, path: Path) -> GeoRef:
        with rasterio.open(path) as ds:
            if ds.crs is None or ds.crs.to_epsg() is None or ds.transform.is_identity:
                raise MissingGeoreferenceError(f"В растре {path.name} нет геопривязки (CRS и transform)")
            return cls(epsg=ds.crs.to_epsg(), transform=ds.transform, width=ds.width, height=ds.height)

    @property
    def gsd(self) -> float:
        return float(abs(self.transform.a))

    @property
    def pixel_area_ha(self) -> float:
        return abs(self.transform.a * self.transform.e) / 10_000.0

    def to_wgs84(self, geom: BaseGeometry) -> BaseGeometry:
        return shapely_transform(_to_wgs84(self.epsg).transform, geom)

    def footprint_utm(self) -> Polygon:
        x0, y0 = self.transform * (0, 0)
        x1, y1 = self.transform * (self.width, self.height)
        return Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])

    def corners_wgs84(self) -> list[list[float]]:
        """Углы в порядке, которого ждёт image-источник MapLibre: TL, TR, BR, BL."""
        ring = list(self.footprint_utm().exterior.coords)[:4]
        lon, lat = _to_wgs84(self.epsg).transform([p[0] for p in ring], [p[1] for p in ring])
        return [[float(x), float(y)] for x, y in zip(lon, lat, strict=True)]

    def pixel_centers(self, rows: np.ndarray, cols: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        xs, ys = self.transform * (cols + 0.5, rows + 0.5)
        return np.asarray(xs), np.asarray(ys)

    def lonlat(self, xs: np.ndarray, ys: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        lon, lat = _to_wgs84(self.epsg).transform(xs, ys)
        return np.asarray(lon), np.asarray(lat)
