"""Эксперименты по модели активного горения: валидация, абляция признаков, сравнение с baseline.

Запуск: uv run python research/af/experiments.py
Метрика везде одна: micro-F1 по всем пикселям выборки. Пиксель горения, не попавший в кандидаты,
считается пропуском, поэтому числа сопоставимы с метрикой соревнования.
"""

from __future__ import annotations

import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

RESULTS = Path("research/af/results")
SEED = 17
N_FOLDS = 5
PARAMS = {
    "objective": "binary",
    "learning_rate": 0.05,
    "num_leaves": 31,
    "min_child_samples": 40,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "reg_lambda": 1.0,
    "n_estimators": 400,
    "random_state": SEED,
    "n_jobs": -1,
    "verbose": -1,
}
THRESHOLDS = np.round(np.arange(0.10, 0.91, 0.01), 2)

RAW = ["i1", "i2", "i3", "i4", "i5", "delta", "night", "solar_zenith", "sensor_zenith"]
CONTEXT = [
    f"{name}_{w}"
    for w in (11, 21, 41)
    for name in (
        "i4_anom",
        "delta_anom",
        "i5_anom",
        "i4_z",
        "delta_z",
        "i5_z",
        "bg_i4_std",
        "bg_delta_std",
        "bg_share",
    )
]
NEIGHBOURS = [
    "hot_neighbours_3",
    "hot_neighbours_7",
    "i4_max_3",
    "delta_max_3",
    "i4_minus_max_5",
    "delta_mean_3",
]
SURFACE = ["landcover", "lc_built_share_5", "lc_water_share_5", "ndvi", "dem"]
WEATHER = ["t2m", "rh2m", "wind"]
SCENE = ["chip_i4_median", "chip_hot_share"]

FEATURE_SETS = {
    "1 каналы": RAW,
    "2 + контекст фона": RAW + CONTEXT,
    "3 + соседи": RAW + CONTEXT + NEIGHBOURS,
    "4 + поверхность": RAW + CONTEXT + NEIGHBOURS + SURFACE,
    "5 + погода": RAW + CONTEXT + NEIGHBOURS + SURFACE + WEATHER,
    "6 + сцена": RAW + CONTEXT + NEIGHBOURS + SURFACE + WEATHER + SCENE,
}


def micro_f1(y: np.ndarray, predicted: np.ndarray, missed_fire: int) -> tuple[float, float, float]:
    tp = int((predicted & (y == 1)).sum())
    fp = int((predicted & (y == 0)).sum())
    fn = int((~predicted & (y == 1)).sum()) + missed_fire
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    return 2 * precision * recall / max(precision + recall, 1e-9), precision, recall


def best_threshold(y: np.ndarray, proba: np.ndarray, missed_fire: int) -> dict[str, float]:
    scores = [micro_f1(y, proba >= t, missed_fire) for t in THRESHOLDS]
    index = int(np.argmax([s[0] for s in scores]))
    f1, precision, recall = scores[index]
    return {
        "f1": round(f1, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "threshold": float(THRESHOLDS[index]),
    }


def oof_predictions(
    candidates: pd.DataFrame, columns: list[str], folds: list[tuple[np.ndarray, np.ndarray]]
) -> np.ndarray:
    proba = np.zeros(len(candidates), dtype=np.float32)
    x, y = candidates[columns].to_numpy(np.float32), candidates.y.to_numpy()
    for train_index, valid_index in folds:
        model = lgb.LGBMClassifier(**PARAMS)
        model.fit(x[train_index], y[train_index])
        proba[valid_index] = model.predict_proba(x[valid_index])[:, 1]
    return proba


def main() -> None:
    pixels = pd.read_pickle(RESULTS / "pixels.pkl")
    candidates = pixels[pixels.candidate].reset_index(drop=True)
    missed_by_chip = pixels[(pixels.y == 1) & ~pixels.candidate].groupby("chip_id").size()
    missed_total = int(missed_by_chip.sum())
    y = candidates.y.to_numpy()

    folds = list(GroupKFold(n_splits=N_FOLDS).split(candidates, y, groups=candidates.footprint))
    report: dict[str, object] = {
        "candidates": len(candidates),
        "fire": int(y.sum()) + missed_total,
        "missed_by_prefilter": missed_total,
    }

    ablation = {}
    for name, columns in FEATURE_SETS.items():
        proba = oof_predictions(candidates, columns, folds)
        ablation[name] = best_threshold(y, proba, missed_total) | {"features": len(columns)}
        print(f"{name:22s} {ablation[name]}")
        if name == list(FEATURE_SETS)[-1]:
            candidates["proba"] = proba
    report["ablation_spatial_cv"] = ablation

    full = FEATURE_SETS[list(FEATURE_SETS)[-1]]
    threshold = ablation[list(FEATURE_SETS)[-1]]["threshold"]
    per_fold = []
    for _, valid_index in folds:
        part = candidates.iloc[valid_index]
        missed = int(missed_by_chip.reindex(part.chip_id.unique()).fillna(0).sum())
        per_fold.append(round(micro_f1(part.y.to_numpy(), part.proba.to_numpy() >= threshold, missed)[0], 4))
    report["per_fold_f1"] = per_fold
    print("по фолдам:", per_fold)

    early, late = candidates.year <= 2021, candidates.year >= 2023
    model = lgb.LGBMClassifier(**PARAMS).fit(
        candidates.loc[early, full].to_numpy(np.float32), y[early.to_numpy()]
    )
    late_part = candidates[late]
    late_missed = int(missed_by_chip.reindex(late_part.chip_id.unique()).fillna(0).sum())
    late_proba = model.predict_proba(late_part[full].to_numpy(np.float32))[:, 1]
    report["temporal_holdout"] = {
        "train": "2019-2021",
        "test": "2023-2024",
        "at_cv_threshold": round(
            micro_f1(late_part.y.to_numpy(), late_proba >= threshold, late_missed)[0], 4
        ),
        "best": best_threshold(late_part.y.to_numpy(), late_proba, late_missed),
    }
    print("временной отложенный:", report["temporal_holdout"])

    slices = {}
    for label, mask in {
        "день": candidates.night == 0,
        "ночь": candidates.night == 1,
        "SNPP": candidates.satellite == "SNPP",
        "NOAA20": candidates.satellite == "NOAA20",
        "NOAA21": candidates.satellite == "NOAA21",
    }.items():
        part = candidates[mask]
        missed = (
            int(missed_by_chip.reindex(part.chip_id.unique()).fillna(0).sum())
            if label in ("SNPP", "NOAA20", "NOAA21")
            else 0
        )
        f1, precision, recall = micro_f1(part.y.to_numpy(), part.proba.to_numpy() >= threshold, missed)
        slices[label] = {
            "f1": round(f1, 4),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "fire": int(part.y.sum()),
        }
    report["slices"] = slices
    print("срезы:", slices)

    candidates[["chip_id", "row", "col", "y", "proba", "footprint", "year", "night", "landcover"]].to_pickle(
        RESULTS / "oof.pkl"
    )
    (RESULTS / "experiments.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
