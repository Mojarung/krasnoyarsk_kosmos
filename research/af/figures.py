"""Графики к отчёту по активному горению. Каждый график отвечает на вопрос, от которого зависело решение.

Запуск: uv run python research/af/figures.py (после experiments.py и experiments_stage2.py)
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from experiments import THRESHOLDS, micro_f1

RESULTS = Path("research/af/results")
FIGURES = Path("research/af/figures")
WEIGHTS = Path("ml/src/fire_ml/weights/af_lgbm.json")
FIRE, OTHER, ACCENT, MUTED = "#e2470f", "#5f7488", "#8f4c25", "#b9ada5"
CHOSEN_THRESHOLD = 0.38
INDEX_BASELINE_F1 = 0.8358

plt.rcParams.update(
    {"font.size": 10, "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 130}
)


def signal_space(pixels: pd.DataFrame) -> None:
    candidates = pixels[pixels.candidate]
    figure, axes = plt.subplots(1, 2, figsize=(10, 4.2), sharey=True)
    for axis, (flag, title) in zip(axes, ((0, "день"), (1, "ночь")), strict=True):
        part = candidates[candidates.night == flag]
        negative, positive = part[part.y == 0], part[part.y == 1]
        axis.scatter(
            negative.i4,
            negative.delta,
            s=3,
            alpha=0.18,
            color=OTHER,
            label=f"не горение, {len(negative)}",
            rasterized=True,
        )
        axis.scatter(
            positive.i4,
            positive.delta,
            s=3,
            alpha=0.35,
            color=FIRE,
            label=f"горение, {len(positive)}",
            rasterized=True,
        )
        axis.set(title=f"Кандидаты, {title}", xlabel="I4, K")
        axis.legend(loc="upper left", frameon=False, markerscale=4)
    axes[0].set_ylabel("I4 - I5, K")
    figure.suptitle("Пороги по I4 и перепаду не разделяют классы: нужен контекст фона", y=1.02)
    figure.savefig(FIGURES / "fig1_signal_space.png", bbox_inches="tight")
    plt.close(figure)


def ablation(report: dict, stage2: dict) -> None:
    items = [(name.split(" ", 1)[1], values["f1"]) for name, values in report["ablation_spatial_cv"].items()]
    items.append(
        ("второй проход по карте вероятностей", stage2["второй проход (признаки + карта вероятностей)"]["f1"])
    )
    labels, scores = zip(*items, strict=True)
    colors = [ACCENT, ACCENT, ACCENT, ACCENT, MUTED, MUTED, MUTED]
    figure, axis = plt.subplots(figsize=(8.6, 3.8))
    bars = axis.barh(labels, scores, color=colors)
    axis.bar_label(bars, fmt="%.4f", padding=4)
    axis.axvline(INDEX_BASELINE_F1, color=OTHER, linestyle="--", linewidth=1)
    axis.text(INDEX_BASELINE_F1 + 0.0005, -0.62, "индексный baseline 0,836", color=OTHER, fontsize=9)
    axis.set(xlim=(0.80, 0.975), xlabel="micro-F1, территориальная кросс-валидация")
    axis.invert_yaxis()
    axis.set_title("Прирост дают контекст, соседи и поверхность. Серое отброшено", loc="left")
    figure.savefig(FIGURES / "fig2_ablation.png", bbox_inches="tight")
    plt.close(figure)


def threshold_curve(oof: pd.DataFrame, missed: int) -> None:
    y, proba = oof.y.to_numpy(), oof.proba_stage1.to_numpy()
    curves = np.array([micro_f1(y, proba >= t, missed) for t in THRESHOLDS])
    figure, axis = plt.subplots(figsize=(7.4, 3.8))
    for column, (label, color) in enumerate((("F1", FIRE), ("точность", ACCENT), ("полнота", OTHER))):
        axis.plot(
            THRESHOLDS, curves[:, column], label=label, color=color, linewidth=2 if column == 0 else 1.2
        )
    plateau = THRESHOLDS[curves[:, 0] >= curves[:, 0].max() - 0.001]
    axis.axvspan(plateau.min(), plateau.max(), color=FIRE, alpha=0.08)
    axis.axvline(CHOSEN_THRESHOLD, color="black", linewidth=0.8, linestyle=":")
    axis.set(
        xlabel="порог вероятности",
        ylim=(0.88, 1.0),
        title=f"F1 плоский на {plateau.min():.2f}-{plateau.max():.2f}, порог {CHOSEN_THRESHOLD} в середине плато",
    )
    axis.legend(frameon=False, loc="lower center", ncols=3)
    figure.savefig(FIGURES / "fig3_threshold.png", bbox_inches="tight")
    plt.close(figure)


def error_structure(oof: pd.DataFrame, pixels: pd.DataFrame) -> None:
    oof = oof.assign(pred=oof.proba_stage1 >= CHOSEN_THRESHOLD)
    fire_sets = {
        cid: set(zip(g.row, g.col, strict=True)) for cid, g in pixels[pixels.y == 1].groupby("chip_id")
    }
    pred_sets = {cid: set(zip(g.row, g.col, strict=True)) for cid, g in oof[oof.pred].groupby("chip_id")}

    def adjacent(sets: dict, frame: pd.DataFrame) -> np.ndarray:
        return np.array(
            [
                any(
                    (r + dr, c + dc) in sets.get(cid, ())
                    for dr in (-1, 0, 1)
                    for dc in (-1, 0, 1)
                    if (dr, dc) != (0, 0)
                )
                for cid, r, c in zip(frame.chip_id, frame.row, frame.col, strict=True)
            ]
        )

    false_pos, false_neg = oof[oof.pred & (oof.y == 0)], oof[~oof.pred & (oof.y == 1)]
    fp_adjacent, fn_adjacent = adjacent(fire_sets, false_pos).mean(), adjacent(pred_sets, false_neg).mean()
    built = {
        "горение в эталоне": (pixels[pixels.y == 1].landcover == 50).mean(),
        "ложные срабатывания": (false_pos.landcover == 50).mean(),
    }

    figure, axes = plt.subplots(1, 2, figsize=(10, 3.6))
    axes[0].barh(
        ["ложные срабатывания", "пропуски"],
        [fp_adjacent, fn_adjacent],
        color=ACCENT,
        label="вплотную к очагу",
    )
    axes[0].barh(
        ["ложные срабатывания", "пропуски"],
        [1 - fp_adjacent, 1 - fn_adjacent],
        left=[fp_adjacent, fn_adjacent],
        color=MUTED,
        label="изолированные",
    )
    axes[0].set(xlim=(0, 1), title=f"Ошибки: {len(false_pos)} ложных, {len(false_neg)} пропусков")
    axes[0].legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.1), ncols=2)
    bars = axes[1].bar(list(built), list(built.values()), color=[FIRE, OTHER], width=0.55)
    axes[1].bar_label(bars, labels=[f"{v:.1%}" for v in built.values()])
    axes[1].set(title="Доля застройки: след вычищенной техногенки", ylim=(0, max(built.values()) * 1.3))
    figure.savefig(FIGURES / "fig4_errors.png", bbox_inches="tight")
    plt.close(figure)


def importance() -> None:
    gain = json.loads(WEIGHTS.read_text("utf-8"))["importance_gain"]
    names, values = zip(*list(gain.items())[:12], strict=True)
    figure, axis = plt.subplots(figsize=(7.4, 4))
    axis.barh(names, values, color=ACCENT)
    axis.invert_yaxis()
    axis.set(xlabel="доля суммарного gain", title="Модель выучила контекстный тест: аномалия I4 над фоном")
    figure.savefig(FIGURES / "fig5_importance.png", bbox_inches="tight")
    plt.close(figure)


def main() -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    pixels = pd.read_pickle(RESULTS / "pixels.pkl")
    oof = pd.read_pickle(RESULTS / "oof_stage2.pkl")
    report = json.loads((RESULTS / "experiments.json").read_text("utf-8"))
    stage2 = json.loads((RESULTS / "experiments_stage2.json").read_text("utf-8"))
    missed = int(((pixels.y == 1) & ~pixels.candidate).sum())

    signal_space(pixels)
    ablation(report, stage2)
    threshold_curve(oof, missed)
    error_structure(oof, pixels)
    importance()
    print("готово:", sorted(p.name for p in FIGURES.glob("*.png")))


if __name__ == "__main__":
    main()
