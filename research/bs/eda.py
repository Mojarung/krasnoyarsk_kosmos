"""Первичный осмотр BS-чипов: формы, типы, диапазоны каналов, баланс классов."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import numpy as np
import rasterio

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else "DATA/fire-train-renamed/train")


def main() -> None:
    kinds = sorted(p.name for p in ROOT.iterdir())
    print("train dirs:", kinds)
    bs = next(ROOT / k for k in kinds if "bs" in k.lower() or "burn" in k.lower())
    print("bs dir:", bs, sorted(p.name for p in bs.iterdir()))
    masks = sorted((bs / "masks").glob("*.tif"))
    print("chips:", len(masks))
    first = masks[0].name.replace("_MASK.tif", "")
    for sub in sorted(p for p in bs.iterdir() if p.is_dir()):
        path = next(sub.glob(f"{first}*"), None)
        if path is None:
            print(f"{sub.name}: нет файла для {first}, всего {len(list(sub.iterdir()))}")
            continue
        with rasterio.open(path) as ds:
            data = ds.read()
            print(
                f"\n{sub.name}: {path.name} shape={data.shape} dtype={data.dtype} nodata={ds.nodata} crs={ds.crs} res={ds.res}"
            )
            print("  descriptions:", ds.descriptions)
            print("  tags:", dict(list(ds.tags().items())[:8]))
            for index, band in enumerate(data):
                finite = band[np.isfinite(band)]
                print(
                    f"  b{index + 1}: min={finite.min():.4g} p50={np.median(finite):.4g} max={finite.max():.4g} nan={np.isnan(band).mean():.3f}"
                )

    shapes, classes = Counter(), Counter()
    for path in masks:
        with rasterio.open(path) as ds:
            mask = ds.read(1)
        shapes[mask.shape] += 1
        values, counts = np.unique(mask, return_counts=True)
        for value, count in zip(values.tolist(), counts.tolist(), strict=True):
            classes[value] += count
    total = sum(classes.values())
    print("\nshapes:", shapes.most_common(6))
    print("classes:", {k: f"{v / total:.4f}" for k, v in sorted(classes.items())})


if __name__ == "__main__":
    main()
