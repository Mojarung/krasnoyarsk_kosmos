"""Попиксельный LightGBM для гарей: GroupKFold по событиям, метрики кейса на OOF, подбор весов классов."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

OUT = Path("research/bs/results")
BS = Path("DATA/fire-train-renamed/train/bs")
N_FOLDS = 5
NEGATIVE_KEEP = 0.2
SEED = 17
PARAMS = {
    "objective": "multiclass",
    "num_class": 4,
    "learning_rate": 0.08,
    "num_leaves": 63,
    "min_child_samples": 200,
    "subsample": 0.7,
    "subsample_freq": 1,
    "colsample_bytree": 0.6,
    "reg_lambda": 2.0,
    "n_estimators": 300,
    "random_state": SEED,
    "n_jobs": 12,
    "verbose": -1,
}


def case_metrics(y: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    burn_true, burn_pred = y > 0, pred > 0
    iou_burn = (burn_true & burn_pred).sum() / max((burn_true | burn_pred).sum(), 1)
    per_class = [((y == c) & (pred == c)).sum() / max(((y == c) | (pred == c)).sum(), 1) for c in (1, 2, 3)]
    return {
        "iou_burn": float(iou_burn),
        "miou_sev": float(np.mean(per_class)),
        "iou_sev": [float(v) for v in per_class],
        "bs_score": float(0.35 * iou_burn + 0.30 * np.mean(per_class)),
    }


def tune_weights(proba: np.ndarray, y: np.ndarray, rounds: int = 2) -> np.ndarray:
    """Argmax по вероятностям не оптимален для IoU: подбираем множители классов координатным спуском."""
    weights = np.ones(4)
    grid = np.array([0.5, 0.65, 0.8, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0])
    best = case_metrics(y, proba.argmax(1))["bs_score"]
    for _ in range(rounds):
        for cls in (1, 2, 3):
            for value in grid:
                trial = weights.copy()
                trial[cls] = value
                score = case_metrics(y, (proba * trial).argmax(1))["bs_score"]
                if score > best:
                    best, weights = score, trial
    return weights


def main() -> None:
    tag = sys.argv[1] if len(sys.argv) > 1 else "full"
    x = np.load(OUT / "pixels_x.npy", mmap_mode="r")
    y = np.load(OUT / "pixels_y.npy").astype(np.int64)
    chip = np.load(OUT / "pixels_chip.npy")
    names = json.loads((OUT / "pixels_features.json").read_text(encoding="utf-8"))
    meta = pd.read_csv(BS / "meta.csv")
    events = meta.fire_event_id.to_numpy()[chip]

    rng = np.random.default_rng(SEED)
    sampled = (y > 0) | (rng.random(y.size) < NEGATIVE_KEEP)
    weight = np.where(y > 0, 1.0, 1.0 / NEGATIVE_KEEP)
    proba = np.zeros((y.size, 4), dtype=np.float32)
    gain = np.zeros(len(names))
    for fold, (train_idx, valid_idx) in enumerate(GroupKFold(N_FOLDS).split(y, y, groups=events)):
        train_idx = train_idx[sampled[train_idx]]
        model = lgb.LGBMClassifier(**PARAMS)
        model.fit(np.asarray(x[train_idx]), y[train_idx], sample_weight=weight[train_idx], feature_name=names)
        proba[valid_idx] = model.predict_proba(np.asarray(x[valid_idx]))
        gain += model.booster_.feature_importance("gain")
        print(f"fold {fold}", case_metrics(y[valid_idx], proba[valid_idx].argmax(1)), flush=True)

    np.save(OUT / f"oof_gbm_{tag}.npy", proba)
    plain = case_metrics(y, proba.argmax(1))
    weights = tune_weights(proba, y)
    tuned = case_metrics(y, (proba * weights).argmax(1))
    importance = dict(
        sorted(zip(names, (gain / gain.sum()).round(4).tolist(), strict=True), key=lambda kv: -kv[1])[:25]
    )
    report = {
        "argmax": plain,
        "class_weights": weights.tolist(),
        "tuned": tuned,
        "importance_gain_top25": importance,
    }
    (OUT / f"gbm_{tag}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
