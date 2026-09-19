"""Боевой LightGBM гарей на всех чипах train. Веса и список признаков кладём в ml/src/fire_ml/weights."""

from __future__ import annotations

import json
from pathlib import Path

import lightgbm as lgb
import numpy as np

from experiments import NEGATIVE_KEEP, OUT, PARAMS, SEED

WEIGHTS = Path("ml/src/fire_ml/weights")


def main() -> None:
    x = np.load(OUT / "pixels_x.npy", mmap_mode="r")
    y = np.load(OUT / "pixels_y.npy").astype(np.int64)
    names = json.loads((OUT / "pixels_features.json").read_text(encoding="utf-8"))
    rng = np.random.default_rng(SEED)
    sampled = np.flatnonzero((y > 0) | (rng.random(y.size) < NEGATIVE_KEEP))
    weight = np.where(y[sampled] > 0, 1.0, 1.0 / NEGATIVE_KEEP)
    model = lgb.LGBMClassifier(**PARAMS | {"deterministic": True, "force_row_wise": True})
    model.fit(np.asarray(x[sampled]), y[sampled], sample_weight=weight, feature_name=names)
    model.booster_.save_model(WEIGHTS / "bs_lgbm.txt")
    (WEIGHTS / "bs_lgbm.json").write_text(
        json.dumps({"features": names, "params": PARAMS, "train_rows": int(sampled.size)}, indent=1),
        encoding="utf-8",
    )
    print("saved", (WEIGHTS / "bs_lgbm.txt").stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
