"""Стекинг: бустинг второго уровня поверх OOF-вероятностей попиксельной модели и сетей.

Линейная смесь не знает, где какой модели верить. Второй уровень видит вероятности обеих моделей,
среднюю вероятность гари от сети в окнах 5, 15 и 41 пиксель и несколько исходных признаков.
Запуск: python research/bs/stack.py <cnn_tag> [<cnn_tag> ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy import ndimage
from sklearn.model_selection import GroupKFold

from blend import compact, tune
from build_dataset import NODATA, STRIDE
from experiments import BS, N_FOLDS, OUT, SEED, case_metrics

WEIGHTS = Path("ml/src/fire_ml/weights")
WINDOWS = (5, 15, 41)
POSITION = ("dist_center", "abs_row", "abs_col")
RAW = ("d_nbr", "d_nbr_mean_5", "d_nbr_mean_15", "landcover", "d_nbr_rank", "post_nbr", "pre_ndvi", "valid")
PARAMS = {
    "objective": "multiclass",
    "num_class": 4,
    "learning_rate": 0.08,
    "num_leaves": 31,
    "min_child_samples": 300,
    "subsample": 0.7,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "reg_lambda": 5.0,
    "n_estimators": 150,
    "random_state": SEED,
    "n_jobs": 10,
    "verbose": -1,
}


def position_layers(shape: tuple[int, int]) -> list[np.ndarray]:
    """Чипы вырезаны вокруг события: доля гари среди высокого dNBR падает с 57% в центре до 20% в углах."""
    rows, cols = np.mgrid[0 : shape[0], 0 : shape[1]].astype(np.float32)
    rows, cols = rows / (shape[0] - 1) - 0.5, cols / (shape[1] - 1) - 0.5
    return [np.hypot(rows, cols), np.abs(rows), np.abs(cols)]


def position_block(masks: np.ndarray) -> np.ndarray:
    parts = []
    layers = position_layers(masks.shape[1:])
    for index in range(len(masks)):
        sl = (slice(index % STRIDE, None, STRIDE), slice((index // STRIDE) % STRIDE, None, STRIDE))
        keep = masks[index][sl].ravel() != NODATA
        parts.append(np.stack([layer[sl].ravel() for layer in layers], axis=1)[keep])
    return np.concatenate(parts)


def cnn_block(volume: np.ndarray, masks: np.ndarray) -> np.ndarray:
    parts = []
    for index in range(len(volume)):
        proba = np.asarray(volume[index], dtype=np.float32)
        burn = 1.0 - proba[0]
        layers = [
            *proba,
            *(ndimage.uniform_filter(burn, window, mode="nearest") for window in WINDOWS),
        ]
        sl = (slice(index % STRIDE, None, STRIDE), slice((index // STRIDE) % STRIDE, None, STRIDE))
        keep = masks[index][sl].ravel() != NODATA
        parts.append(np.stack([layer[sl].ravel() for layer in layers], axis=1)[keep])
    return np.concatenate(parts)


def main() -> None:
    tags = sys.argv[1:]
    names = json.loads((OUT / "pixels_features.json").read_text(encoding="utf-8"))
    y = np.load(OUT / "pixels_y.npy").astype(np.int64)
    chip = np.load(OUT / "pixels_chip.npy")
    events = pd.read_csv(BS / "meta.csv").fire_event_id.to_numpy()[chip]
    x = np.load(OUT / "pixels_x.npy", mmap_mode="r")
    candidates = np.flatnonzero(
        (np.asarray(x[:, names.index("d_nbr")]) > 0.06)
        | (np.asarray(x[:, names.index("d_nbr_mean_5")]) > 0.06)
    )

    masks = np.load(OUT / "cnn_cache.npz")["y"]
    # Каждая сеть идёт своими признаками: при усреднении слабая тянула сильную вниз (0,460 против 0,467).
    cnn = np.concatenate(
        [cnn_block(np.load(OUT / f"oof_cnn_{tag}.npy", mmap_mode="r"), masks) for tag in tags]
        + [position_block(masks)],
        axis=1,
    )
    raw = np.stack([np.asarray(x[:, names.index(name)]) for name in RAW], axis=1)
    table = np.concatenate([np.load(OUT / "oof_gbm_full.npy"), cnn, raw], axis=1)[candidates]
    columns = [
        *(f"gbm_p{c}" for c in range(4)),
        *(
            name
            for tag in tags
            for name in (*(f"{tag}_p{c}" for c in range(4)), *(f"{tag}_burn_{w}" for w in WINDOWS))
        ),
        *POSITION,
        *RAW,
    ]
    target, groups = y[candidates], events[candidates]
    print("stack rows", table.shape, flush=True)

    proba = np.zeros((y.size, 4), dtype=np.float32)
    proba[:, 0] = 1.0
    fold_of = np.full(y.size, -1, dtype=np.int8)
    for fold, (train_idx, valid_idx) in enumerate(GroupKFold(N_FOLDS).split(target, groups=groups)):
        model = lgb.LGBMClassifier(**PARAMS).fit(table[train_idx], target[train_idx], feature_name=columns)
        proba[candidates[valid_idx]] = model.predict_proba(table[valid_idx])
        fold_of[candidates[valid_idx]] = fold
        print("fold", fold, flush=True)
    weights, metrics = tune(proba, y)
    report = {"class_weights": weights.round(3).tolist(), **metrics}
    # Фон вне кандидатов относим к фолду по событию, иначе IoU по фолду считался бы без части пикселей.
    event_fold = {e: f for e, f in zip(groups, fold_of[candidates], strict=True)}
    fold_all = np.array([event_fold.get(e, -1) for e in events])
    report["by_fold"] = [
        compact(case_metrics(y[fold_all == f], (proba[fold_all == f] * weights).argmax(1)))
        for f in range(N_FOLDS)
    ]
    for f, row in enumerate(report["by_fold"]):
        print("  fold", f, row, flush=True)
    print("STACK", weights.round(2).tolist(), compact(metrics), flush=True)

    final = lgb.LGBMClassifier(**PARAMS | {"deterministic": True, "force_row_wise": True}).fit(
        table, target, feature_name=columns
    )
    gain = final.booster_.feature_importance("gain")
    report["importance_gain"] = dict(
        sorted(zip(columns, (gain / gain.sum()).round(4).tolist(), strict=True), key=lambda kv: -kv[1])
    )
    final.booster_.save_model(WEIGHTS / "bs_stack.txt")
    (WEIGHTS / "bs_stack.json").write_text(
        json.dumps(
            {
                "features": columns,
                "raw": list(RAW),
                "windows": list(WINDOWS),
                "class_weights": report["class_weights"],
                "cnn_tags": tags,
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    (OUT / f"stack_{'+'.join(tags)}.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report["importance_gain"], indent=1))


if __name__ == "__main__":
    main()
