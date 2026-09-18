"""Индексный baseline без обучения. Заглушка до подключения обученных моделей."""

from __future__ import annotations

import numpy as np
from scipy import ndimage

from fire_ml.contract import AfChip, AfCode, AfPrediction, BsChip, BsPrediction

LC_TREES, LC_SHRUB, LC_GRASS, LC_CROP, LC_BUILT, LC_BARE, LC_WATER, LC_WETLAND = (
    10,
    20,
    30,
    40,
    50,
    60,
    80,
    90,
)

NIGHT_SOLAR_ZENITH_DEG = 88.0
CONTEXT_WINDOW_PX = 21
DAY_I4_MIN_K, DAY_DELTA_MIN_K = 325.0, 20.0
NIGHT_I4_MIN_K, NIGHT_DELTA_MIN_K = 300.0, 10.0
ABSOLUTE_I4_K = 355.0
CONTEXT_SIGMA = 3.0
GLINT_I3_REFLECTANCE = 0.35

SCL_INVALID = (0, 1, 3, 8, 9, 10, 11)
S2_SCALE = 10000.0
B8A, B12 = 6, 8
DNBR_THRESHOLDS = {
    "woody": (0.10, 0.27, 0.66),
    "herbaceous": (0.07, 0.16, 0.28),
}
MIN_BURN_COMPONENT_PX = 25


def _context_stats(values: np.ndarray, background: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    weights = ndimage.uniform_filter(background.astype(np.float32), CONTEXT_WINDOW_PX, mode="nearest")
    weights = np.maximum(weights, 1e-6)
    filled = np.where(background, values, 0.0).astype(np.float32)
    mean = ndimage.uniform_filter(filled, CONTEXT_WINDOW_PX, mode="nearest") / weights
    mean_sq = ndimage.uniform_filter(filled**2, CONTEXT_WINDOW_PX, mode="nearest") / weights
    std = np.sqrt(np.maximum(mean_sq - mean**2, 0.0))
    return mean, std


class BaselineActiveFire:
    name = "baseline-contextual-v0"

    def predict(self, chip: AfChip) -> AfPrediction:
        i3, i4, i5 = chip.viirs[2], chip.viirs[3], chip.viirs[4]
        solar_zenith = chip.viirs[5]
        landcover = chip.aux[0]
        valid = (chip.viirs[7] > 0.5) & np.isfinite(i4) & np.isfinite(i5)
        i4 = np.where(valid, i4, 0.0)
        delta = np.where(valid, i4 - i5, 0.0)
        night = solar_zenith >= NIGHT_SOLAR_ZENITH_DEG

        i4_min = np.where(night, NIGHT_I4_MIN_K, DAY_I4_MIN_K)
        delta_min = np.where(night, NIGHT_DELTA_MIN_K, DAY_DELTA_MIN_K)
        potential = valid & (i4 > i4_min) & (delta > delta_min)

        background = valid & ~potential
        i4_mean, i4_std = _context_stats(i4, background)
        d_mean, d_std = _context_stats(delta, background)
        contextual = (i4 > i4_mean + CONTEXT_SIGMA * i4_std) & (delta > d_mean + CONTEXT_SIGMA * d_std)
        hot = potential & (contextual | (i4 >= ABSOLUTE_I4_K))

        glint = hot & ~night & ((landcover == LC_WATER) | (np.nan_to_num(i3) > GLINT_I3_REFLECTANCE))
        technogenic = hot & ~glint & (landcover == LC_BUILT)
        fire = hot & ~glint & ~technogenic

        codes = np.zeros(i4.shape, dtype=np.uint8)
        codes[fire] = AfCode.FIRE
        codes[technogenic] = AfCode.TECHNOGENIC
        codes[glint] = AfCode.GLINT
        spread = np.maximum(d_std, 1.0)
        confidence = np.clip((delta - d_mean) / (8.0 * spread), 0.0, 1.0).astype(np.float32)
        return AfPrediction(fire_mask=fire.astype(np.uint8), codes=codes, confidence=confidence)


def nbr(s2: np.ndarray) -> np.ndarray:
    nir = s2[B8A].astype(np.float32) / S2_SCALE
    swir = s2[B12].astype(np.float32) / S2_SCALE
    return (nir - swir) / np.maximum(nir + swir, 1e-6)


def valid_pair(s2_pre: np.ndarray, s2_post: np.ndarray) -> np.ndarray:
    scl_ok = ~np.isin(s2_pre[9], SCL_INVALID) & ~np.isin(s2_post[9], SCL_INVALID)
    return scl_ok & (s2_pre[B8A] > 0) & (s2_post[B8A] > 0)


class BaselineBurnSeverity:
    name = "baseline-dnbr-landcover-v0"

    def predict(self, chip: BsChip) -> BsPrediction:
        dnbr = nbr(chip.s2_pre) - nbr(chip.s2_post)
        landcover = chip.aux[2]
        valid = valid_pair(chip.s2_pre, chip.s2_post) & ~np.isin(landcover, (LC_WATER, LC_BUILT, LC_BARE))
        woody = np.isin(landcover, (LC_TREES, LC_SHRUB))

        severity = np.zeros(dnbr.shape, dtype=np.uint8)
        for is_group, key in ((woody, "woody"), (~woody, "herbaceous")):
            low, mid, high = DNBR_THRESHOLDS[key]
            area = valid & is_group
            severity[area & (dnbr >= low)] = 1
            severity[area & (dnbr >= mid)] = 2
            severity[area & (dnbr >= high)] = 3

        labels, _ = ndimage.label(severity > 0)
        sizes = np.bincount(labels.ravel())
        small = sizes < MIN_BURN_COMPONENT_PX
        small[0] = False
        severity[small[labels]] = 0
        return BsPrediction(severity=severity, dnbr=dnbr.astype(np.float32))
