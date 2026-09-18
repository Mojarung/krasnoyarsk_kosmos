"""Вторая серия: отбор признаков, гиперпараметры, второй проход по карте вероятностей.

Запуск: uv run python research/af/experiments_stage2.py
"""

from __future__ import annotations

import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy import ndimage
from sklearn.model_selection import GroupKFold

from experiments import (
    CONTEXT,
    N_FOLDS,
    NEIGHBOURS,
    PARAMS,
    RAW,
    SURFACE,
    best_threshold,
    micro_f1,
    oof_predictions,
)

RESULTS = Path("research/af/results")
CHIP_SIZE = 256
_RING = np.ones((3, 3), dtype=np.float32)
_RING[1, 1] = 0.0

STAGE2 = ["p", "p_max_3", "p_mean_3", "p_count_3", "p_max_5", "p_mean_5"]


def probability_context(frame: pd.DataFrame, proba: np.ndarray) -> pd.DataFrame:
    """Статистики вероятностей первого прохода вокруг каждого кандидата."""
    out = np.zeros((len(frame), len(STAGE2)), dtype=np.float32)
    for _, index in frame.groupby("chip_id").indices.items():
        rows, cols = frame.row.to_numpy()[index], frame.col.to_numpy()[index]
        grid = np.zeros((CHIP_SIZE, CHIP_SIZE), dtype=np.float32)
        grid[rows, cols] = proba[index]
        neighbours_max = ndimage.maximum_filter(grid, footprint=_RING.astype(bool), mode="constant")
        neighbours_mean = ndimage.convolve(grid, _RING / 8.0, mode="constant")
        count = ndimage.convolve((grid >= 0.5).astype(np.float32), _RING, mode="constant")
        max_5 = ndimage.maximum_filter(grid, size=5, mode="constant")
        mean_5 = ndimage.uniform_filter(grid, 5, mode="constant")
        out[index] = np.stack(
            [
                grid[rows, cols],
                neighbours_max[rows, cols],
                neighbours_mean[rows, cols],
                count[rows, cols],
                max_5[rows, cols],
                mean_5[rows, cols],
            ],
            axis=1,
        )
    return pd.DataFrame(out, columns=STAGE2, index=frame.index)


def main() -> None:
    pixels = pd.read_pickle(RESULTS / "pixels.pkl")
    candidates = pixels[pixels.candidate].reset_index(drop=True)
    missed = int(((pixels.y == 1) & ~pixels.candidate).sum())
    y = candidates.y.to_numpy()
    folds = list(GroupKFold(n_splits=N_FOLDS).split(candidates, y, groups=candidates.footprint))
    report: dict[str, object] = {}

    selection = {
        "каналы + контекст + поверхность": RAW + CONTEXT + SURFACE,
        "каналы + контекст + соседи + поверхность": RAW + CONTEXT + NEIGHBOURS + SURFACE,
    }
    for name, columns in selection.items():
        report[name] = best_threshold(y, oof_predictions(candidates, columns, folds), missed)
        print(f"{name:44s} {report[name]}")

    final = RAW + CONTEXT + NEIGHBOURS + SURFACE
    for label, override in {
        "глубже: 63 листа, 800 деревьев, lr 0.03": {
            "num_leaves": 63,
            "n_estimators": 800,
            "learning_rate": 0.03,
        },
        "проще: 15 листьев, 300 деревьев": {"num_leaves": 15, "n_estimators": 300},
    }.items():
        proba = np.zeros(len(candidates), dtype=np.float32)
        x = candidates[final].to_numpy(np.float32)
        for train_index, valid_index in folds:
            model = lgb.LGBMClassifier(**(PARAMS | override)).fit(x[train_index], y[train_index])
            proba[valid_index] = model.predict_proba(x[valid_index])[:, 1]
        report[label] = best_threshold(y, proba, missed)
        print(f"{label:44s} {report[label]}")

    stage1 = oof_predictions(candidates, final, folds)
    report["первый проход"] = best_threshold(y, stage1, missed)
    context = probability_context(candidates, stage1)
    stacked = pd.concat([candidates[[*final, "chip_id", "row", "col", "footprint", "y"]], context], axis=1)
    stage2 = oof_predictions(stacked, final + STAGE2, folds)
    report["второй проход (признаки + карта вероятностей)"] = best_threshold(y, stage2, missed)
    print(f"{'первый проход':44s} {report['первый проход']}")
    print(f"{'второй проход':44s} {report['второй проход (признаки + карта вероятностей)']}")

    threshold = report["второй проход (признаки + карта вероятностей)"]["threshold"]
    per_fold_1, per_fold_2 = [], []
    for _, valid_index in folds:
        chips = set(candidates.chip_id.iloc[valid_index])
        fold_missed = int(((pixels.y == 1) & ~pixels.candidate & pixels.chip_id.isin(chips)).sum())
        per_fold_1.append(
            round(
                micro_f1(
                    y[valid_index], stage1[valid_index] >= report["первый проход"]["threshold"], fold_missed
                )[0],
                4,
            )
        )
        per_fold_2.append(
            round(micro_f1(y[valid_index], stage2[valid_index] >= threshold, fold_missed)[0], 4)
        )
    report["по фолдам, первый проход"] = per_fold_1
    report["по фолдам, второй проход"] = per_fold_2
    print("по фолдам 1:", per_fold_1, "\nпо фолдам 2:", per_fold_2)

    candidates.assign(proba_stage1=stage1, proba_stage2=stage2)[
        [
            "chip_id",
            "row",
            "col",
            "y",
            "proba_stage1",
            "proba_stage2",
            "night",
            "landcover",
            "footprint",
            "year",
        ]
    ].to_pickle(RESULTS / "oof_stage2.pkl")
    (RESULTS / "experiments_stage2.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
