"""CPU-часть обработки сцены. Чистые функции: файлы на входе, готовые записи на выходе."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from fire_ml import ActiveFireModel, AfCode, BurnSeverityModel
from fire_ml.baseline import NIGHT_SOLAR_ZENITH_DEG, nbr
from fire_ml.io import load_af_chip, load_bs_chip, read_raster
from firewatch.domain.catalog import lc_group
from firewatch.pipeline import quicklook
from firewatch.pipeline.georef import GeoRef
from firewatch.pipeline.vectorize import BurnShape, SeverityShape, vectorize_severity

MASK_NODATA = 255


@dataclass(frozen=True)
class AfResult:
    georef: GeoRef
    model_name: str
    hotspots: list[dict[str, Any]]
    quicklooks: dict[str, bytes]
    stats: dict[str, Any]


@dataclass(frozen=True)
class BsResult:
    georef: GeoRef
    model_name: str
    burn_shapes: list[BurnShape]
    severity_shapes: list[SeverityShape]
    landcover_ha: dict[tuple[int, str], float]
    quicklooks: dict[str, bytes]
    stats: dict[str, Any] = field(default_factory=dict)


def compute_af(chip_id: str, paths: dict[str, Path], model: ActiveFireModel) -> AfResult:
    georef = GeoRef.from_raster(paths["viirs"])
    chip = load_af_chip(chip_id, paths)
    prediction = model.predict(chip)
    codes = prediction.resolved_codes()

    rows, cols = np.nonzero(codes)
    xs, ys = georef.pixel_centers(rows, cols)
    lon, lat = georef.lonlat(xs, ys) if rows.size else (np.array([]), np.array([]))
    confidence = (
        prediction.confidence if prediction.confidence is not None else np.ones(codes.shape, np.float32)
    )
    viirs, aux = chip.viirs, chip.aux

    hotspots = [
        {
            "lon": float(lon[i]),
            "lat": float(lat[i]),
            "x_utm": round(float(xs[i])),
            "y_utm": round(float(ys[i])),
            "code": int(codes[r, c]),
            "bt_i4": float(viirs[3, r, c]),
            "bt_i5": float(viirs[4, r, c]),
            "confidence": float(confidence[r, c]),
            "landcover": int(aux[0, r, c]),
            "is_night": bool(viirs[5, r, c] >= NIGHT_SOLAR_ZENITH_DEG),
            "t2m": _finite(aux[2, r, c]),
            "rh2m": _finite(aux[3, r, c]),
            "wind_speed": _finite(aux[4, r, c]),
        }
        for i, (r, c) in enumerate(zip(rows.tolist(), cols.tolist(), strict=True))
    ]

    stats: dict[str, Any] = {
        "fire_px": int((codes == AfCode.FIRE).sum()),
        "technogenic_px": int((codes == AfCode.TECHNOGENIC).sum()),
        "glint_px": int((codes == AfCode.GLINT).sum()),
    }
    if (mask_path := paths.get("mask")) and mask_path.exists():
        stats["quality"] = {"fire": _confusion(codes == AfCode.FIRE, read_raster(mask_path)[0] == 1)}

    looks = {"thermal": quicklook.thermal_image(viirs[3], viirs[7] > 0.5)}
    return AfResult(georef=georef, model_name=model.name, hotspots=hotspots, quicklooks=looks, stats=stats)


def compute_bs(
    chip_id: str, paths: dict[str, Path], model: BurnSeverityModel, min_polygon_px: int
) -> BsResult:
    georef = GeoRef.from_raster(paths["s2_post"])
    chip = load_bs_chip(chip_id, paths)
    prediction = model.predict(chip)
    severity = np.where(np.isin(prediction.severity, (1, 2, 3)), prediction.severity, 0).astype(np.uint8)
    burn_shapes, severity_shapes = vectorize_severity(severity, georef.transform, min_polygon_px)

    landcover = chip.aux[2]
    landcover_ha: dict[tuple[int, str], float] = {}
    for klass in (1, 2, 3):
        values, counts = np.unique(landcover[severity == klass], return_counts=True)
        for value, count in zip(values.tolist(), counts.tolist(), strict=True):
            key = (klass, lc_group(value))
            landcover_ha[key] = landcover_ha.get(key, 0.0) + count * georef.pixel_area_ha

    dnbr = prediction.dnbr if prediction.dnbr is not None else nbr(chip.s2_pre) - nbr(chip.s2_post)
    rgb_pre, rgb_post = quicklook.optical_pair(chip.s2_pre, chip.s2_post, quicklook.TRUE_COLOR)
    swir_pre, swir_post = quicklook.optical_pair(chip.s2_pre, chip.s2_post, quicklook.SWIR_COMPOSITE)
    sar_pre, sar_post = quicklook.sar_pair(chip.s1_pre, chip.s1_post)
    looks = {
        "rgb_pre": rgb_pre,
        "rgb_post": rgb_post,
        "swir_pre": swir_pre,
        "swir_post": swir_post,
        "sar_pre": sar_pre,
        "sar_post": sar_post,
        "dnbr": quicklook.dnbr_image(dnbr),
        "severity": quicklook.severity_image(severity),
    }

    stats: dict[str, Any] = {
        "burn_ha": round(sum(b.area_ha for b in burn_shapes), 2),
        "severity_ha": [round(sum(b.severity_ha[k] for b in burn_shapes), 2) for k in range(3)],
        "contours": len(burn_shapes),
    }
    if (mask_path := paths.get("mask")) and mask_path.exists():
        reference = read_raster(mask_path)[0]
        known = reference != MASK_NODATA
        stats["quality"] = {
            "burn": _confusion((severity > 0) & known, (reference > 0) & known),
            "severity": [_confusion((severity == k) & known, (reference == k) & known) for k in (1, 2, 3)],
        }
    return BsResult(
        georef=georef,
        model_name=model.name,
        burn_shapes=burn_shapes,
        severity_shapes=severity_shapes,
        landcover_ha=landcover_ha,
        quicklooks=looks,
        stats=stats,
    )


def _confusion(predicted: np.ndarray, reference: np.ndarray) -> dict[str, int]:
    return {
        "tp": int((predicted & reference).sum()),
        "fp": int((predicted & ~reference).sum()),
        "fn": int((~predicted & reference).sum()),
    }


def _finite(value: float) -> float | None:
    return float(value) if np.isfinite(value) else None
