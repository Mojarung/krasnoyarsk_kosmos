"""Обучает боевую модель активного горения на всём train и сохраняет веса.

Запуск: uv run python research/af/build_dataset.py && uv run python research/af/train.py
Результат: ml/src/fire_ml/weights/af_lgbm.txt и af_lgbm.json (признаки, порог, параметры).
Порог и состав признаков выбраны в experiments.py и experiments_stage2.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from experiments import CONTEXT, NEIGHBOURS, PARAMS, RAW, SURFACE

PIXELS = Path("research/af/results/pixels.pkl")
WEIGHTS = Path("ml/src/fire_ml/weights")
FEATURES = RAW + CONTEXT + NEIGHBOURS + SURFACE
THRESHOLD = 0.38


def main() -> None:
    pixels = pd.read_pickle(PIXELS)
    candidates = pixels[pixels.candidate]
    params = PARAMS | {"deterministic": True, "force_row_wise": True}
    model = lgb.LGBMClassifier(**params)
    model.fit(candidates[FEATURES].to_numpy(np.float32), candidates.y.to_numpy(), feature_name=FEATURES)

    WEIGHTS.mkdir(parents=True, exist_ok=True)
    model.booster_.save_model(str(WEIGHTS / "af_lgbm.txt"))
    gain = model.booster_.feature_importance(importance_type="gain")
    card = {
        "features": FEATURES,
        "threshold": THRESHOLD,
        "params": {k: v for k, v in params.items() if k not in ("n_jobs", "verbose")},
        "train_candidates": len(candidates),
        "train_fire_pixels": int(candidates.y.sum()),
        "importance_gain": dict(
            sorted(zip(FEATURES, (gain / gain.sum()).round(4).tolist(), strict=True), key=lambda kv: -kv[1])
        ),
    }
    (WEIGHTS / "af_lgbm.json").write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    top = list(card["importance_gain"].items())[:8]
    print(f"обучено на {len(candidates)} кандидатах, {card['train_fire_pixels']} пикселей горения")
    print("важность по gain:", top)


if __name__ == "__main__":
    main()
