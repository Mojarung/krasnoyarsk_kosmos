"""Как эталонные степени связаны с dNBR, RdNBR и RBR: квантили по классам и покрову."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import rasterio

BS = Path("DATA/fire-train-renamed/train/bs")
STRIDE = 4


def read(sub: str, chip: str, suffix: str) -> np.ndarray:
    with rasterio.open(BS / sub / f"{chip}_{suffix}.tif") as ds:
        return ds.read().astype(np.float32)


def nbr(s2: np.ndarray) -> np.ndarray:
    nir, swir = s2[6], s2[8]
    return (nir - swir) / np.maximum(nir + swir, 1.0)


def main() -> None:
    meta = pd.read_csv(BS / "meta.csv")
    print(
        meta[["fire_event_id", "region", "date_pre", "date_post", "cloud_frac"]]
        .describe(include="all")
        .T.head(8)
    )
    print(
        "events:",
        meta.fire_event_id.nunique(),
        "| chips per event max:",
        meta.fire_event_id.value_counts().max(),
    )
    rows = []
    for chip in meta.chip_id:
        pre, post = (
            read("sentinel2_pre", chip, "Sentinel-2_pre"),
            read("sentinel2_post", chip, "Sentinel-2_post"),
        )
        aux, mask = read("_aux", chip, "AUX"), read("masks", chip, "MASK")[0]
        a, b = nbr(pre), nbr(post)
        dnbr = a - b
        sl = (slice(None, None, STRIDE), slice(None, None, STRIDE))
        rows.append(
            pd.DataFrame(
                {
                    "chip": chip,
                    "y": mask[sl].ravel(),
                    "dnbr": dnbr[sl].ravel(),
                    "rbr": (dnbr / (a + 1.001))[sl].ravel(),
                    "rdnbr": (dnbr / np.sqrt(np.maximum(np.abs(a), 0.05)))[sl].ravel(),
                    "nbr_post": b[sl].ravel(),
                    "lc": aux[2][sl].ravel(),
                    "scl_post": post[9][sl].ravel(),
                }
            )
        )
    frame = pd.concat(rows, ignore_index=True)
    print("mask values:", frame.y.value_counts().to_dict())
    quantiles = [0.05, 0.25, 0.5, 0.75, 0.95]
    for column in ["dnbr", "rbr", "rdnbr", "nbr_post"]:
        print(f"\n{column} по классам")
        print(frame.groupby("y")[column].quantile(quantiles).unstack().round(3))
    burned = frame[frame.y.isin([1, 2, 3])]
    print("\ndNBR медиана по покрову и степени")
    print(burned.pivot_table(index="lc", columns="y", values="dnbr", aggfunc="median").round(3))
    print("\nплощадь по покрову и степени, доли")
    print(pd.crosstab(burned.lc, burned.y, normalize="index").round(3))
    print("\nSCL post у гари:", burned.scl_post.value_counts(normalize=True).round(3).to_dict())
    per_chip = burned.groupby(["chip", "y"]).dnbr.median().unstack()
    print("\nразброс медианы dNBR между чипами (std):", per_chip.std().round(3).to_dict())
    frame.to_parquet("research/bs/results/label_probe.parquet")


if __name__ == "__main__":
    Path("research/bs/results").mkdir(parents=True, exist_ok=True)
    main()
