"""Попиксельные признаки для детекции активного горения по VIIRS I1-I5.

Один и тот же код считает признаки в исследовании и на инференсе.
Контекстные признаки повторяют логику VNP14IMG (Schroeder et al., 2014): пиксель сравнивается
со статистикой фона в скользящем окне, из которого исключены заведомо горячие пиксели.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage

from fire_ml.contract import AfChip

NIGHT_SOLAR_ZENITH_DEG = 88.0
WINDOWS = (11, 21, 41)
BACKGROUND_EXCLUDE_DAY = (335.0, 30.0)
BACKGROUND_EXCLUDE_NIGHT = (300.0, 10.0)
MIN_BACKGROUND_SHARE = 0.25
LANDCOVER_CODES = (10, 20, 30, 40, 50, 60, 80, 90)

CANDIDATE_I4_DAY_K = 315.0
CANDIDATE_I4_NIGHT_K = 290.0
CANDIDATE_DELTA_DAY_K = 12.0
CANDIDATE_DELTA_NIGHT_K = 6.0
CANDIDATE_Z = 2.0
# Внутри крупного пожара соседи раздувают разброс фона и z-оценка падает: таких берём по абсолютным порогам.
LARGE_FIRE_I4_K = 330.0
LARGE_FIRE_DELTA_K = 25.0
# Насыщенный I4 «заворачивается» в низкие значения, перепад I4-I5 становится отрицательным. Выдаёт его горячий I5.
FOLDED_I5_K = 320.0
FOLDED_I5_Z = 3.0
FOLDED_NEIGHBOUR_I4_K = 335.0

_NEIGHBOURS_3 = np.ones((3, 3), dtype=np.float32)
_NEIGHBOURS_3[1, 1] = 0.0


def _masked_mean_std(
    values: np.ndarray, mask: np.ndarray, size: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    share = ndimage.uniform_filter(mask.astype(np.float32), size, mode="nearest")
    safe = np.maximum(share, 1e-6)
    filled = np.where(mask, values, 0.0).astype(np.float32)
    mean = ndimage.uniform_filter(filled, size, mode="nearest") / safe
    mean_sq = ndimage.uniform_filter(filled * filled, size, mode="nearest") / safe
    return mean, np.sqrt(np.maximum(mean_sq - mean * mean, 0.0)), share


def _ratio(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
    return numerator / np.maximum(np.abs(denominator), 1e-3)


def compute_features(chip: AfChip) -> tuple[dict[str, np.ndarray], np.ndarray]:
    """Возвращает словарь признаков (каждый HxW, float32) и маску пикселей-кандидатов."""
    viirs, aux = chip.viirs, chip.aux
    valid = (viirs[7] > 0.5) & np.isfinite(viirs[3]) & np.isfinite(viirs[4])
    i1, i2, i3 = (np.nan_to_num(viirs[k]).astype(np.float32) for k in range(3))
    i4 = np.where(valid, viirs[3], 0.0).astype(np.float32)
    i5 = np.where(valid, viirs[4], 0.0).astype(np.float32)
    delta = i4 - i5
    solar_zenith = np.nan_to_num(viirs[5], nan=90.0).astype(np.float32)
    night = solar_zenith >= NIGHT_SOLAR_ZENITH_DEG

    i4_limit = np.where(night, BACKGROUND_EXCLUDE_NIGHT[0], BACKGROUND_EXCLUDE_DAY[0])
    delta_limit = np.where(night, BACKGROUND_EXCLUDE_NIGHT[1], BACKGROUND_EXCLUDE_DAY[1])
    background = valid & ~((i4 > i4_limit) & (delta > delta_limit))

    features: dict[str, np.ndarray] = {
        "i1": i1,
        "i2": i2,
        "i3": i3,
        "i4": i4,
        "i5": i5,
        "delta": delta,
        "ndvi": _ratio(i2 - i1, i2 + i1),
        "solar_zenith": solar_zenith,
        "sensor_zenith": np.nan_to_num(viirs[6]).astype(np.float32),
        "night": night.astype(np.float32),
        "dem": np.nan_to_num(aux[1]).astype(np.float32),
        "t2m": np.nan_to_num(aux[2]).astype(np.float32),
        "rh2m": np.nan_to_num(aux[3]).astype(np.float32),
        "wind": np.nan_to_num(aux[4]).astype(np.float32),
    }
    landcover = np.nan_to_num(aux[0]).astype(np.int16)
    features["landcover"] = landcover.astype(np.float32)

    z_by_window = []
    for size in WINDOWS:
        i4_mean, i4_std, share = _masked_mean_std(i4, background, size)
        d_mean, d_std, _ = _masked_mean_std(delta, background, size)
        i5_mean, i5_std, _ = _masked_mean_std(i5, background, size)
        features[f"i4_anom_{size}"] = i4 - i4_mean
        features[f"delta_anom_{size}"] = delta - d_mean
        features[f"i5_anom_{size}"] = i5 - i5_mean
        features[f"i4_z_{size}"] = _ratio(i4 - i4_mean, np.maximum(i4_std, 0.5))
        features[f"delta_z_{size}"] = _ratio(delta - d_mean, np.maximum(d_std, 0.5))
        features[f"i5_z_{size}"] = _ratio(i5 - i5_mean, np.maximum(i5_std, 0.5))
        features[f"bg_i4_std_{size}"] = i4_std
        features[f"bg_delta_std_{size}"] = d_std
        features[f"bg_share_{size}"] = share
        z_by_window.append((features[f"i4_z_{size}"], features[f"delta_z_{size}"]))

    hot = valid & (features["delta_z_21"] > CANDIDATE_Z) & (features["i4_z_21"] > CANDIDATE_Z)
    hot_f = hot.astype(np.float32)
    features["hot_neighbours_3"] = ndimage.convolve(hot_f, _NEIGHBOURS_3, mode="constant")
    features["hot_neighbours_7"] = ndimage.uniform_filter(hot_f, 7, mode="constant") * 49.0 - hot_f
    features["i4_max_3"] = ndimage.maximum_filter(i4, size=3, mode="nearest")
    features["delta_max_3"] = ndimage.maximum_filter(delta, size=3, mode="nearest")
    features["i4_minus_max_5"] = i4 - ndimage.maximum_filter(i4, size=5, mode="nearest")
    features["delta_mean_3"] = ndimage.uniform_filter(delta, 3, mode="nearest")
    features["lc_built_share_5"] = ndimage.uniform_filter(
        (landcover == 50).astype(np.float32), 5, mode="nearest"
    )
    features["lc_water_share_5"] = ndimage.uniform_filter(
        (landcover == 80).astype(np.float32), 5, mode="nearest"
    )

    valid_values = i4[valid]
    features["chip_i4_median"] = np.full(
        i4.shape, np.median(valid_values) if valid_values.size else 0.0, np.float32
    )
    features["chip_hot_share"] = np.full(i4.shape, float(hot.mean()), np.float32)

    i4_floor = np.where(night, CANDIDATE_I4_NIGHT_K, CANDIDATE_I4_DAY_K)
    delta_floor = np.where(night, CANDIDATE_DELTA_NIGHT_K, CANDIDATE_DELTA_DAY_K)
    contextual = features["delta_z_21"] > CANDIDATE_Z
    inside_large_fire = (i4 > LARGE_FIRE_I4_K) & (delta > LARGE_FIRE_DELTA_K)
    folded = (
        (i5 > FOLDED_I5_K)
        & (features["i5_z_21"] > FOLDED_I5_Z)
        & (features["i4_max_3"] > FOLDED_NEIGHBOUR_I4_K)
    )
    candidates = valid & (
        ((i4 > i4_floor) & (delta > delta_floor) & (contextual | inside_large_fire)) | folded
    )
    return features, candidates


def feature_names(features: dict[str, np.ndarray]) -> list[str]:
    return list(features)


def to_matrix(features: dict[str, np.ndarray], mask: np.ndarray, names: list[str]) -> np.ndarray:
    return np.stack([features[name][mask] for name in names], axis=1).astype(np.float32)
