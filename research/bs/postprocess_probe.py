"""Проба постобработки: убирать связные пятна гари без ядра средней или сильной степени.

OOF стекинга лежит на сетке с шагом 3, поэтому связность считается на ней же (пиксель 60 м).
"""

from __future__ import annotations

import sys

import numpy as np
from scipy import ndimage

from build_dataset import STRIDE
from experiments import OUT, case_metrics

SIDE = 512


def grids(values: np.ndarray, chip: np.ndarray, masks: np.ndarray) -> list[tuple[np.ndarray, np.ndarray]]:
    out, cursor = [], 0
    for index in range(len(masks)):
        sl = (slice(index % STRIDE, None, STRIDE), slice((index // STRIDE) % STRIDE, None, STRIDE))
        keep = masks[index][sl] != 255
        grid = np.zeros(keep.shape, dtype=values.dtype)
        grid[keep] = values[cursor : cursor + keep.sum()]
        cursor += int(keep.sum())
        out.append((grid, keep))
    assert cursor == len(values)
    return out


def main() -> None:
    tag = sys.argv[1]
    y = np.load(OUT / "pixels_y.npy").astype(np.int64)
    chip = np.load(OUT / "pixels_chip.npy")
    masks = np.load(OUT / "cnn_cache.npz")["y"]
    proba = np.load(OUT / f"oof_stack_{tag}.npy")
    pred = (proba * np.array([1.0, 1.8, 1.8, 1.8])).argmax(1)
    print("без постобработки", case_metrics(y, pred))
    structure = np.ones((3, 3), dtype=bool)
    for min_core_share, min_size in (
        (0.0, 5),
        (0.0, 20),
        (0.02, 0),
        (0.05, 0),
        (0.1, 0),
        (0.2, 0),
        (0.05, 10),
        (0.1, 20),
    ):
        result = []
        for grid, keep in grids(pred, chip, masks):
            labels, count = ndimage.label(grid > 0, structure=structure)
            if count:
                ids = np.arange(1, count + 1)
                size = ndimage.sum(grid > 0, labels, ids)
                core = ndimage.sum(grid >= 2, labels, ids)
                drop = ids[(core / size < min_core_share) | (size < min_size)]
                grid = np.where(np.isin(labels, drop), 0, grid)
            result.append(grid[keep])
        metrics = case_metrics(y, np.concatenate(result))
        print(
            f"доля ядра >= {min_core_share}, размер >= {min_size}: burn {metrics['iou_burn']:.4f} sev {metrics['miou_sev']:.4f} score {metrics['bs_score']:.4f}"
        )


if __name__ == "__main__":
    main()
