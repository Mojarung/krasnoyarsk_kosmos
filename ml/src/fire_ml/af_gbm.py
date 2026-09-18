"""Боевая модель активного горения: предфильтр кандидатов + LightGBM по контекстным признакам.

Обоснование состава признаков, порога и отказа от второго прохода: research/af/REPORT.md.
"""

from __future__ import annotations

import json
from importlib import resources

import lightgbm as lgb
import numpy as np

from fire_ml.af_features import compute_features, to_matrix
from fire_ml.contract import AfChip, AfCode, AfPrediction

LC_BUILT, LC_WATER = 50, 80
GLINT_I3_REFLECTANCE = 0.35


class GbmActiveFire:
    name = "lgbm-contextual-v1"

    def __init__(self) -> None:
        weights = resources.files("fire_ml.weights")
        card = json.loads(weights.joinpath("af_lgbm.json").read_text("utf-8"))
        self._features: list[str] = card["features"]
        self._threshold: float = card["threshold"]
        self._booster = lgb.Booster(model_str=weights.joinpath("af_lgbm.txt").read_text("utf-8"))

    def predict(self, chip: AfChip) -> AfPrediction:
        features, candidates = compute_features(chip)
        shape = candidates.shape
        confidence = np.zeros(shape, dtype=np.float32)
        if candidates.any():
            confidence[candidates] = self._booster.predict(to_matrix(features, candidates, self._features))
        fire = confidence >= self._threshold

        rejected = candidates & ~fire
        day = features["night"] < 0.5
        glint = (
            rejected & day & ((features["landcover"] == LC_WATER) | (features["i3"] > GLINT_I3_REFLECTANCE))
        )
        technogenic = rejected & ~glint & (features["landcover"] == LC_BUILT)

        codes = np.zeros(shape, dtype=np.uint8)
        codes[fire] = AfCode.FIRE
        codes[technogenic] = AfCode.TECHNOGENIC
        codes[glint] = AfCode.GLINT
        return AfPrediction(fire_mask=fire.astype(np.uint8), codes=codes, confidence=confidence)
