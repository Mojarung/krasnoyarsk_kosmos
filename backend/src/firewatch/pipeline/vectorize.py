from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np
from affine import Affine
from rasterio.features import shapes
from scipy import ndimage
from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.ops import unary_union

SEVERITY_CLASSES = (1, 2, 3)
_LABEL_SHIFT = 4
_EIGHT_CONNECTED = np.ones((3, 3), dtype=bool)
M2_PER_HA = 10_000.0


@dataclass(frozen=True)
class SeverityShape:
    burn_label: int
    severity: int
    geom_utm: Polygon
    area_ha: float


@dataclass(frozen=True)
class BurnShape:
    label: int
    geom_utm: MultiPolygon
    area_ha: float
    severity_ha: tuple[float, float, float]


def vectorize_severity(
    severity: np.ndarray, transform: Affine, min_polygon_px: int = 1
) -> tuple[list[BurnShape], list[SeverityShape]]:
    """Маска 0..3 -> контуры гарей и полигоны степеней в метрической проекции чипа.

    Полигоны идут по границам пикселей без упрощения, поэтому площадь вектора равна
    числу пикселей, умноженному на площадь пикселя, и справка сходится с растром.
    """
    burn = np.isin(severity, SEVERITY_CLASSES)
    if not burn.any():
        return [], []
    labels, _ = ndimage.label(burn, structure=_EIGHT_CONNECTED)
    combined = (labels.astype(np.int32) * _LABEL_SHIFT + severity.astype(np.int32)).astype(np.int32)
    min_area_m2 = min_polygon_px * abs(transform.a * transform.e)

    severity_shapes: list[SeverityShape] = []
    by_label: dict[int, list[SeverityShape]] = defaultdict(list)
    for geom, value in shapes(combined, mask=burn, transform=transform, connectivity=4):
        polygon = shape(geom)
        if polygon.area < min_area_m2:
            continue
        item = SeverityShape(
            burn_label=int(value) // _LABEL_SHIFT,
            severity=int(value) % _LABEL_SHIFT,
            geom_utm=polygon,
            area_ha=polygon.area / M2_PER_HA,
        )
        severity_shapes.append(item)
        by_label[item.burn_label].append(item)

    burn_shapes = [_merge(label, parts) for label, parts in sorted(by_label.items())]
    return burn_shapes, severity_shapes


def _merge(label: int, parts: list[SeverityShape]) -> BurnShape:
    merged = unary_union([p.geom_utm for p in parts])
    multi = merged if isinstance(merged, MultiPolygon) else MultiPolygon([merged])
    by_severity = tuple(sum(p.area_ha for p in parts if p.severity == k) for k in SEVERITY_CLASSES)
    return BurnShape(label=label, geom_utm=multi, area_ha=sum(by_severity), severity_ha=by_severity)
