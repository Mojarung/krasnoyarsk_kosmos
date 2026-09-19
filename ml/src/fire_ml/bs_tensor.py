"""Многоканальный тензор чипа гарей для свёрточной сети. Масштабы фиксированы, статистик train не требуют."""

from __future__ import annotations

import numpy as np
from scipy import ndimage

from fire_ml.bs_features import SCL_INVALID, indices
from fire_ml.bs_rule import label_rule, lower_threshold, smooth_dnbr
from fire_ml.contract import BsChip

LANDCOVER_CLASSES = (10, 20, 30, 40, 50, 60, 80, 90)
DELTA_INDICES = ("nbr", "nbr2", "ndvi", "ndmi", "ndre")
# Тень, растительность, грунт, вода, облака трёх видов, снег: эталон по-разному обходится с каждым классом.
SCL_CLASSES = (3, 4, 5, 6, 8, 9, 10, 11)
N_CHANNELS = 9 + 9 + len(DELTA_INDICES) + 3 + 4 + 3 + 2 + len(LANDCOVER_CLASSES) + 2
N_RULE_CHANNELS = 4 + 1 + 2 * len(SCL_CLASSES)
N_CHANNELS_V2 = N_CHANNELS + N_RULE_CHANNELS


def chip_tensor(chip: BsChip) -> np.ndarray:
    pre = chip.s2_pre[:9].astype(np.float32) / 10000.0
    post = chip.s2_post[:9].astype(np.float32) / 10000.0
    idx_pre, idx_post = indices(pre), indices(post)
    scl_pre, scl_post = chip.s2_pre[9], chip.s2_post[9]
    sar_pre, sar_post = chip.s1_pre.astype(np.float32) / 100.0, chip.s1_post.astype(np.float32) / 100.0
    dem = chip.aux[0].astype(np.float32)
    landcover = chip.aux[2]

    dnbr = idx_pre["nbr"] - idx_post["nbr"]
    channels = [
        *(np.clip(pre, 0, 1) * 3.0),
        *(np.clip(post, 0, 1) * 3.0),
        *((idx_pre[name] - idx_post[name]) * 2.0 for name in DELTA_INDICES),
        idx_post["nbr"],
        idx_pre["nbr"],
        (dnbr - np.median(dnbr)) * 2.0,
        *((sar_pre + 15.0) / 10.0),
        *((sar_post + 15.0) / 10.0),
        ndimage.uniform_filter(sar_post[0] - sar_pre[0], 7, mode="nearest") / 3.0,
        ndimage.uniform_filter(sar_post[1] - sar_pre[1], 7, mode="nearest") / 3.0,
        ndimage.uniform_filter((sar_post[0] - sar_post[1]) - (sar_pre[0] - sar_pre[1]), 7, mode="nearest")
        / 3.0,
        (dem - np.median(dem)) / 50.0,
        chip.aux[1].astype(np.float32) / 30.0,
        *((landcover == cls).astype(np.float32) for cls in LANDCOVER_CLASSES),
        np.isin(scl_pre, SCL_INVALID).astype(np.float32),
        np.isin(scl_post, SCL_INVALID).astype(np.float32),
    ]
    tensor = np.stack(channels).astype(np.float32)
    return np.nan_to_num(np.clip(tensor, -6.0, 6.0))


def rule_tensor(chip: BsChip) -> np.ndarray:
    """Каналы правила разметки: сеть не тратит ёмкость на пороги и маски SCL, ей остаётся буфер события."""
    nbr_pre = indices(chip.s2_pre[:9].astype(np.float32))["nbr"]
    nbr_post = indices(chip.s2_post[:9].astype(np.float32))["nbr"]
    landcover = chip.aux[2]
    scl_pre, scl_post = chip.s2_pre[9], chip.s2_post[9]
    severity = label_rule(nbr_pre, nbr_post, landcover, scl_pre, scl_post)
    margin = np.clip((smooth_dnbr(nbr_pre - nbr_post) - lower_threshold(landcover)) * 5.0, -2.0, 2.0)
    channels = [
        *((severity == cls).astype(np.float32) for cls in range(4)),
        margin,
        *((scl_pre == cls).astype(np.float32) for cls in SCL_CLASSES),
        *((scl_post == cls).astype(np.float32) for cls in SCL_CLASSES),
    ]
    return np.nan_to_num(np.stack(channels).astype(np.float32))


def chip_tensor_v2(chip: BsChip) -> np.ndarray:
    return np.concatenate([chip_tensor(chip), rule_tensor(chip)])
