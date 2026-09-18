"""Собирает попиксельный датасет для модели активного горения.

Запуск: uv run python research/af/build_dataset.py
Результат: research/af/results/pixels.pkl (кандидаты, все эталонные пиксели горения, выборка фона).
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd

from fire_ml.af_features import compute_features
from fire_ml.io import chip_paths, load_af_chip, read_raster

DATA = Path("DATA/fire-train-renamed/train/af")
OUT = Path("research/af/results/pixels.pkl")
BACKGROUND_PER_CHIP = 150
SEED = 17


def main() -> None:
    meta = pd.read_csv(DATA / "meta.csv")
    meta["when"] = pd.to_datetime(meta.acq_datetime)
    meta["footprint"] = (
        meta.epsg.astype(int).astype(str)
        + "_"
        + meta.x_min.astype(int).astype(str)
        + "_"
        + meta.y_min.astype(int).astype(str)
    )
    rng = np.random.default_rng(SEED)
    frames = []
    started = time.perf_counter()

    for row in meta.itertuples():
        paths = chip_paths(DATA, row.chip_id, "af")
        chip = load_af_chip(row.chip_id, paths)
        truth = read_raster(paths["mask"])[0] == 1
        features, candidates = compute_features(chip)

        background = np.zeros_like(truth)
        free = np.flatnonzero(~(candidates | truth).ravel())
        background.ravel()[rng.choice(free, size=min(BACKGROUND_PER_CHIP, free.size), replace=False)] = True

        keep = candidates | truth | background
        rows, cols = np.nonzero(keep)
        frame = pd.DataFrame({name: values[keep] for name, values in features.items()})
        frame.insert(0, "chip_id", row.chip_id)
        frame["row"], frame["col"] = rows.astype(np.int16), cols.astype(np.int16)
        frame["y"] = truth[keep].astype(np.int8)
        frame["candidate"] = candidates[keep]
        frame["footprint"] = row.footprint
        frame["year"] = row.when.year
        frame["satellite"] = row.satellite
        frames.append(frame)

    pixels = pd.concat(frames, ignore_index=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    pixels.to_pickle(OUT)

    fire = pixels[pixels.y == 1]
    cand = pixels[pixels.candidate]
    print(
        f"чипов {len(meta)}, время {time.perf_counter() - started:.1f} с, {1000 * (time.perf_counter() - started) / len(meta):.0f} мс на чип"
    )
    print(f"строк {len(pixels)}, пикселей горения {len(fire)}, кандидатов {len(cand)}")
    print(
        f"покрытие горения кандидатами: {fire.candidate.mean():.4f}, доля горения среди кандидатов: {cand.y.mean():.4f}"
    )
    print(
        f"потолок F1 при идеальном классификаторе кандидатов: {2 * fire.candidate.mean() / (1 + fire.candidate.mean()):.4f}"
    )


if __name__ == "__main__":
    main()
