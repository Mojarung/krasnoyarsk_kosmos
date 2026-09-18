from __future__ import annotations

from io import BytesIO

import numpy as np
from PIL import Image

from firewatch.domain.catalog import SEVERITY_COLORS

WEBP_QUALITY = 86
STRETCH_PERCENTILES = (2.0, 98.0)
TRUE_COLOR = (2, 1, 0)
SWIR_COMPOSITE = (8, 6, 2)
SEVERITY_ALPHA = 215

DNBR_STOPS = (
    (-0.25, (44, 123, 182)),
    (0.0, (28, 30, 38)),
    (0.15, (255, 209, 102)),
    (0.4, (247, 127, 0)),
    (0.8, (157, 2, 8)),
)
THERMAL_STOPS = (
    (0.0, (8, 6, 24)),
    (0.35, (74, 12, 107)),
    (0.6, (188, 55, 84)),
    (0.8, (249, 142, 9)),
    (1.0, (252, 255, 164)),
)


def _encode(rgb: np.ndarray, *, lossless: bool = False) -> bytes:
    buffer = BytesIO()
    Image.fromarray(rgb).save(buffer, format="WEBP", quality=WEBP_QUALITY, lossless=lossless, method=4)
    return buffer.getvalue()


def _colorize(values: np.ndarray, stops: tuple[tuple[float, tuple[int, int, int]], ...]) -> np.ndarray:
    positions = [s[0] for s in stops]
    channels = [np.interp(values, positions, [s[1][c] for s in stops]) for c in range(3)]
    return np.stack(channels, axis=-1).astype(np.uint8)


def _stretch_limits(*images: np.ndarray, bands: tuple[int, ...]) -> list[tuple[float, float]]:
    limits = []
    for band in bands:
        sample = np.concatenate([img[band][img[band] > 0].ravel() for img in images])
        if sample.size == 0:
            limits.append((0.0, 1.0))
            continue
        low, high = np.percentile(sample, STRETCH_PERCENTILES)
        limits.append((float(low), float(max(high, low + 1.0))))
    return limits


def _composite(image: np.ndarray, bands: tuple[int, ...], limits: list[tuple[float, float]]) -> bytes:
    layers = [
        np.clip((image[band].astype(np.float32) - low) / (high - low), 0.0, 1.0) ** 0.85
        for band, (low, high) in zip(bands, limits, strict=True)
    ]
    return _encode((np.stack(layers, axis=-1) * 255).astype(np.uint8))


def optical_pair(pre: np.ndarray, post: np.ndarray, bands: tuple[int, ...]) -> tuple[bytes, bytes]:
    """Общая растяжка гистограммы для обеих дат: иначе сравнение «до/после» искажается."""
    limits = _stretch_limits(pre, post, bands=bands)
    return _composite(pre, bands, limits), _composite(post, bands, limits)


def sar_pair(pre: np.ndarray, post: np.ndarray) -> tuple[bytes, bytes]:
    def stack(s1: np.ndarray) -> np.ndarray:
        vv, vh = s1[0].astype(np.float32) / 100.0, s1[1].astype(np.float32) / 100.0
        return np.stack([vv, vh, vv - vh])

    a, b = stack(pre), stack(post)
    limits = []
    for band in range(3):
        sample = np.concatenate([a[band].ravel(), b[band].ravel()])
        low, high = np.percentile(sample, STRETCH_PERCENTILES)
        limits.append((float(low), float(max(high, low + 0.1))))

    def render(img: np.ndarray) -> bytes:
        layers = [np.clip((img[i] - lo) / (hi - lo), 0.0, 1.0) for i, (lo, hi) in enumerate(limits)]
        return _encode((np.stack(layers, axis=-1) * 255).astype(np.uint8))

    return render(a), render(b)


def dnbr_image(dnbr: np.ndarray) -> bytes:
    return _encode(_colorize(np.nan_to_num(dnbr), DNBR_STOPS))


def severity_image(severity: np.ndarray) -> bytes:
    rgba = np.zeros((*severity.shape, 4), dtype=np.uint8)
    for klass, color in SEVERITY_COLORS.items():
        rgba[severity == klass] = (*color, SEVERITY_ALPHA)
    return _encode(rgba, lossless=True)


def thermal_image(i4: np.ndarray, valid: np.ndarray) -> bytes:
    finite = np.where(valid & np.isfinite(i4), i4, np.nan)
    low, high = np.nanpercentile(finite, (1.0, 99.8)) if np.isfinite(finite).any() else (270.0, 330.0)
    scaled = np.clip((np.nan_to_num(finite, nan=low) - low) / max(high - low, 1.0), 0.0, 1.0)
    return _encode(_colorize(scaled, THERMAL_STOPS))
