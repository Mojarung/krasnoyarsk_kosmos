"""Снимок после пожара, dNBR и эталон рядом: откуда берётся граница гари и степени."""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from matplotlib.colors import ListedColormap

BS = Path("DATA/fire-train-renamed/train/bs")
FIGURES = Path("research/bs/figures")
SEVERITY = ListedColormap(["#1b1b1b", "#f2cf72", "#ee8a35", "#d2382f"])


def read(sub: str, chip: str, suffix: str) -> np.ndarray:
    with rasterio.open(BS / sub / f"{chip}_{suffix}.tif") as ds:
        return ds.read().astype(np.float32)


def composite(s2: np.ndarray) -> np.ndarray:
    rgb = np.stack([s2[8], s2[6], s2[2]], axis=-1) / 10000.0
    return np.clip(rgb / np.percentile(rgb, 99), 0, 1)


def main() -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    meta = pd.read_csv(BS / "meta.csv")
    chips = sys.argv[1:] or meta.sort_values("burn_area_ha").chip_id.iloc[[30, 90, 150, 200, 220]].tolist()
    figure, axes = plt.subplots(len(chips), 4, figsize=(16, 4 * len(chips)))
    for row, chip in zip(axes, chips, strict=True):
        pre, post = (
            read("sentinel2_pre", chip, "Sentinel-2_pre"),
            read("sentinel2_post", chip, "Sentinel-2_post"),
        )
        mask = read("masks", chip, "MASK")[0]
        dnbr = (pre[6] - pre[8]) / np.maximum(pre[6] + pre[8], 1) - (post[6] - post[8]) / np.maximum(
            post[6] + post[8], 1
        )
        info = meta.set_index("chip_id").loc[chip]
        row[0].imshow(composite(pre))
        row[0].set_title(f"{chip} до, {info.date_pre}")
        row[1].imshow(composite(post))
        row[1].set_title(f"после, {info.date_post}")
        row[2].imshow(dnbr, cmap="RdYlBu_r", vmin=-0.3, vmax=0.8)
        row[2].set_title("dNBR")
        row[3].imshow(np.where(mask == 255, 0, mask), cmap=SEVERITY, vmin=0, vmax=3, interpolation="nearest")
        row[3].set_title(f"эталон, {info.burn_area_ha:.0f} га")
        for axis in row:
            axis.axis("off")
    figure.tight_layout()
    figure.savefig(FIGURES / "look_chips.png", dpi=70)


if __name__ == "__main__":
    main()
