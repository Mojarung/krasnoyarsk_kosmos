"""Попиксельный датасет гарей: признаки из fire_ml.bs_features на прореженной сетке."""

from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio

from fire_ml.bs_features import compute_features
from fire_ml.io import chip_paths, load_bs_chip

BS = Path("DATA/fire-train-renamed/train/bs")
OUT = Path("research/bs/results")
STRIDE = 3
NODATA = 255


def one_chip(args: tuple[int, str]) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    index, chip_id = args
    paths = chip_paths(BS, chip_id, "bs")
    features = compute_features(load_bs_chip(chip_id, paths))
    with rasterio.open(paths["mask"]) as ds:
        mask = ds.read(1)
    offset = index % STRIDE
    sl = (slice(offset, None, STRIDE), slice((index // STRIDE) % STRIDE, None, STRIDE))
    names = list(features)
    x = np.stack([features[name][sl].ravel() for name in names], axis=1)
    y = mask[sl].ravel()
    keep = y != NODATA
    return x[keep], y[keep], np.full(int(keep.sum()), index, dtype=np.int32), names


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    meta = pd.read_csv(BS / "meta.csv")
    with ProcessPoolExecutor(max_workers=10) as pool:
        parts = list(pool.map(one_chip, enumerate(meta.chip_id), chunksize=4))
    names = parts[0][3]
    x = np.concatenate([p[0] for p in parts])
    y = np.concatenate([p[1] for p in parts]).astype(np.int8)
    chip = np.concatenate([p[2] for p in parts])
    np.save(OUT / "pixels_x.npy", x)
    np.save(OUT / "pixels_y.npy", y)
    np.save(OUT / "pixels_chip.npy", chip)
    (OUT / "pixels_features.json").write_text(json.dumps(names), encoding="utf-8")
    print("rows", x.shape, "classes", np.bincount(y).tolist())


if __name__ == "__main__":
    main()
