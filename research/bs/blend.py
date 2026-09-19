"""Смешивание OOF-вероятностей бустинга и U-Net: вес сети, множители классов, метрики кейса.

OOF бустинга лежит на прореженной сетке, поэтому вероятности сети берём в тех же пикселях.
Запуск: python research/bs/blend.py <cnn_tag> [<cnn_tag> ...]
"""

from __future__ import annotations

import json
import sys

import numpy as np

from build_dataset import NODATA, STRIDE
from experiments import OUT, case_metrics

BURN_GRID = (1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.5, 8.0)
CLASS_GRID = (0.6, 0.75, 0.9, 1.0, 1.15, 1.3, 1.6, 2.0)


def sample_like_gbm(volume: np.ndarray, masks: np.ndarray) -> np.ndarray:
    parts = []
    for index in range(len(volume)):
        sl = (slice(index % STRIDE, None, STRIDE), slice((index // STRIDE) % STRIDE, None, STRIDE))
        keep = masks[index][sl].ravel() != NODATA
        parts.append(volume[index][(slice(None), *sl)].reshape(volume.shape[1], -1).T[keep])
    return np.concatenate(parts).astype(np.float32)


def tune(proba: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, dict]:
    """Сначала общий множитель «гарь против фона», затем поправки по степеням."""
    best_w, best = np.ones(4), case_metrics(y, proba.argmax(1))
    for burn in BURN_GRID:
        trial = np.array([1.0, burn, burn, burn])
        metrics = case_metrics(y, (proba * trial).argmax(1))
        if metrics["bs_score"] > best["bs_score"]:
            best_w, best = trial, metrics
    for _ in range(2):
        for cls in (1, 2, 3):
            base = best_w.copy()
            for factor in CLASS_GRID:
                trial = base.copy()
                trial[cls] = base[cls] * factor
                metrics = case_metrics(y, (proba * trial).argmax(1))
                if metrics["bs_score"] > best["bs_score"]:
                    best_w, best = trial, metrics
    return best_w, best


def compact(metrics: dict) -> dict:
    return {
        k: (round(v, 4) if isinstance(v, float) else [round(i, 4) for i in v]) for k, v in metrics.items()
    }


def main() -> None:
    tags = sys.argv[1:]
    y = np.load(OUT / "pixels_y.npy").astype(np.int64)
    gbm = np.load(OUT / "oof_gbm_full.npy")
    masks = np.load(OUT / "cnn_cache.npz")["y"]
    cnn = np.mean(
        [sample_like_gbm(np.load(OUT / f"oof_cnn_{tag}.npy", mmap_mode="r"), masks) for tag in tags], axis=0
    )
    assert len(cnn) == len(y), (len(cnn), len(y))

    report = {}
    for share in (0.0, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
        weights, metrics = tune(share * cnn + (1 - share) * gbm, y)
        report[f"cnn_share_{share}"] = {"class_weights": weights.round(3).tolist(), **metrics}
        print("flat", share, weights.round(2).tolist(), compact(metrics), flush=True)

    # Иерархически: контур гари из смеси, степень внутри контура по отдельной смеси с меньшей долей сети.
    for burn_share in (0.5, 0.6, 0.7, 0.8):
        for sev_share in (0.0, 0.2, 0.4):
            burn = burn_share * cnn + (1 - burn_share) * gbm
            sev = sev_share * cnn + (1 - sev_share) * gbm
            sev = sev[:, 1:] / np.maximum(sev[:, 1:].sum(1, keepdims=True), 1e-6)
            proba = np.concatenate([burn[:, :1], (1 - burn[:, :1]) * sev], axis=1)
            weights, metrics = tune(proba, y)
            report[f"hier_{burn_share}_{sev_share}"] = {"class_weights": weights.round(3).tolist(), **metrics}
            print("hier", burn_share, sev_share, weights.round(2).tolist(), compact(metrics), flush=True)
    (OUT / f"blend_{'+'.join(tags)}.json").write_text(json.dumps(report, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
