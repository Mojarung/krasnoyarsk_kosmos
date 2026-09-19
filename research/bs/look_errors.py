"""Худшие чипы: снимок до и после, эталон, прогноз сети вне обучения."""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio

from figures import SEVERITY
from look import BS, composite, read

OUT = Path("research/bs/results")


def main() -> None:
    chips = sys.argv[1:]
    meta = pd.read_csv(BS / "meta.csv")
    index = {c: i for i, c in enumerate(meta.chip_id)}
    oof = [np.load(OUT / f"oof_cnn_{t}.npy", mmap_mode="r") for t in ("unet_mitb2", "unet_mitb2_s2")]
    figure, axes = plt.subplots(len(chips), 5, figsize=(20, 4 * len(chips)))
    for row, chip in zip(axes, chips, strict=True):
        pre, post = (
            read("sentinel2_pre", chip, "Sentinel-2_pre"),
            read("sentinel2_post", chip, "Sentinel-2_post"),
        )
        with rasterio.open(BS / "masks" / f"{chip}_MASK.tif") as ds:
            mask = ds.read(1)
        proba = np.mean([np.asarray(v[index[chip]], dtype=np.float32) for v in oof], axis=0)
        info = meta.set_index("chip_id").loc[chip]
        true_rgb = lambda s2: np.clip(np.stack([s2[2], s2[1], s2[0]], -1) / 3000.0, 0, 1)  # noqa: E731
        for axis, image, title in (
            (row[0], composite(pre), f"{chip} до {info.date_pre}"),
            (row[1], composite(post), f"после {info.date_post}"),
            (row[2], true_rgb(post), "после, натуральные цвета"),
        ):
            axis.imshow(image)
            axis.set_title(title)
        row[3].imshow(np.where(mask == 255, 0, mask), cmap=SEVERITY, vmin=0, vmax=3, interpolation="nearest")
        row[3].set_title(f"эталон, событие {info.fire_event_id}")
        row[4].imshow(proba.argmax(0), cmap=SEVERITY, vmin=0, vmax=3, interpolation="nearest")
        row[4].set_title("сеть вне обучения")
        for axis in row:
            axis.axis("off")
    figure.tight_layout()
    figure.savefig("research/bs/figures/look_errors.png", dpi=60)


if __name__ == "__main__":
    main()
