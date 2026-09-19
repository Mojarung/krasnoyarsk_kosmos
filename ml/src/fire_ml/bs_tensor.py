"""Многоканальный тензор чипа гарей для свёрточной сети. Масштабы фиксированы, статистик train не требуют."""

from __future__ import annotations

import numpy as np
from scipy import ndimage

from fire_ml.bs_features import SCL_INVALID, indices
from fire_ml.contract import BsChip

LANDCOVER_CLASSES = (10, 20, 30, 40, 50, 60, 80, 90)
DELTA_INDICES = ("nbr", "nbr2", "ndvi", "ndmi", "ndre")
N_CHANNELS = 9 + 9 + len(DELTA_INDICES) + 3 + 4 + 3 + 2 + len(LANDCOVER_CLASSES) + 2


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
