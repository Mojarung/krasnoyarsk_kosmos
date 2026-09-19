"""Попиксельные признаки для гарей. Один код на обучении и на инференсе.

Эталонные степени не совпадают с фиксированными порогами dNBR: медианы плывут по покрову и от события
к событию. Поэтому рядом с индексами идут контекст окна и положение пикселя внутри своего чипа.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage

from fire_ml.contract import BsChip

S2_BANDS = ("b2", "b3", "b4", "b5", "b6", "b7", "b8a", "b11", "b12")
SCL_INVALID = (0, 1, 3, 8, 9, 10, 11)
WINDOWS = (5, 15, 41)
REFLECTANCE_SCALE = 10000.0
SAR_SCALE = 100.0


def _ratio(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return (a - b) / np.maximum(a + b, 1e-3)


def indices(s2: np.ndarray) -> dict[str, np.ndarray]:
    b = dict(zip(S2_BANDS, s2[:9], strict=True))
    return {
        "nbr": _ratio(b["b8a"], b["b12"]),
        "nbr2": _ratio(b["b11"], b["b12"]),
        "ndvi": _ratio(b["b8a"], b["b4"]),
        "ndmi": _ratio(b["b8a"], b["b11"]),
        "ndre": _ratio(b["b8a"], b["b5"]),
        "mirbi": 10.0 * b["b12"] - 9.8 * b["b11"] + 2.0,
        "bright": (b["b2"] + b["b3"] + b["b4"]) / 3.0,
    }


def _rank_in_chip(values: np.ndarray, valid: np.ndarray) -> np.ndarray:
    flat = values.ravel()
    order = np.argsort(flat, kind="stable")
    ranks = np.empty(flat.size, dtype=np.float32)
    ranks[order] = np.linspace(0.0, 1.0, flat.size, dtype=np.float32)
    return np.where(valid, ranks.reshape(values.shape), np.float32(0.5))


def compute_features(chip: BsChip) -> dict[str, np.ndarray]:
    pre = chip.s2_pre[:9].astype(np.float32) / REFLECTANCE_SCALE
    post = chip.s2_post[:9].astype(np.float32) / REFLECTANCE_SCALE
    scl_pre, scl_post = chip.s2_pre[9].astype(np.int16), chip.s2_post[9].astype(np.int16)
    valid = ~(np.isin(scl_pre, SCL_INVALID) | np.isin(scl_post, SCL_INVALID))

    features: dict[str, np.ndarray] = {}
    for index, name in enumerate(S2_BANDS):
        features[f"pre_{name}"] = pre[index]
        features[f"post_{name}"] = post[index]
        features[f"d_{name}"] = post[index] - pre[index]

    idx_pre, idx_post = indices(pre), indices(post)
    for name in idx_pre:
        features[f"pre_{name}"] = idx_pre[name]
        features[f"post_{name}"] = idx_post[name]
        features[f"d_{name}"] = idx_pre[name] - idx_post[name]

    dnbr = features["d_nbr"]
    features["rbr"] = dnbr / (idx_pre["nbr"] + 1.001)
    features["rdnbr"] = dnbr / np.sqrt(np.maximum(np.abs(idx_pre["nbr"]), 0.05))

    sar_pre, sar_post = (
        chip.s1_pre.astype(np.float32) / SAR_SCALE,
        chip.s1_post.astype(np.float32) / SAR_SCALE,
    )
    for index, name in enumerate(("vv", "vh")):
        features[f"pre_{name}"] = sar_pre[index]
        features[f"post_{name}"] = sar_post[index]
        features[f"d_{name}_smooth"] = ndimage.uniform_filter(
            sar_post[index] - sar_pre[index], 7, mode="nearest"
        )
    features["d_cross_smooth"] = ndimage.uniform_filter(
        (sar_post[0] - sar_post[1]) - (sar_pre[0] - sar_pre[1]), 7, mode="nearest"
    )

    features["dem"] = chip.aux[0].astype(np.float32)
    features["slope"] = chip.aux[1].astype(np.float32)
    features["landcover"] = chip.aux[2].astype(np.float32)
    features["scl_pre"] = scl_pre.astype(np.float32)
    features["scl_post"] = scl_post.astype(np.float32)
    features["valid"] = valid.astype(np.float32)

    for window in WINDOWS:
        for name in ("d_nbr", "d_ndvi", "post_nbr", "post_mirbi"):
            features[f"{name}_mean_{window}"] = ndimage.uniform_filter(features[name], window, mode="nearest")
    mean5 = features["d_nbr_mean_5"]
    features["d_nbr_std_5"] = np.sqrt(
        np.maximum(ndimage.uniform_filter(dnbr * dnbr, 5, mode="nearest") - mean5 * mean5, 0.0)
    )
    features["d_nbr_max_5"] = ndimage.maximum_filter(dnbr, 5, mode="nearest")
    features["d_nbr_min_5"] = ndimage.minimum_filter(dnbr, 5, mode="nearest")

    reference = dnbr[valid] if valid.any() else dnbr.ravel()
    for quantile in (50, 90, 99):
        features[f"chip_d_nbr_p{quantile}"] = np.full(
            dnbr.shape, np.percentile(reference, quantile), dtype=np.float32
        )
    features["d_nbr_offset"] = dnbr - features["chip_d_nbr_p50"]
    features["d_nbr_rank"] = _rank_in_chip(dnbr, valid)
    features["post_nbr_rank"] = _rank_in_chip(-idx_post["nbr"], valid)
    features["chip_pre_ndvi_p50"] = np.full(dnbr.shape, np.median(idx_pre["ndvi"]), dtype=np.float32)
    features["chip_valid_share"] = np.full(dnbr.shape, valid.mean(), dtype=np.float32)
    return {name: np.asarray(value, dtype=np.float32) for name, value in features.items()}
