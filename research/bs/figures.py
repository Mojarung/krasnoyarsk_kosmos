"""Графики для отчёта по гарям. Каждый отвечает на один вопрос, заголовок формулирует вывод."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import ListedColormap

OUT = Path("research/bs/results")
FIGURES = Path("research/bs/figures")
ACCENT, MUTED, FIRE, OTHER = "#8f4c25", "#b9aba2", "#e2470f", "#5f7488"
SEVERITY = ListedColormap(["#1b1b1b", "#f2cf72", "#ee8a35", "#d2382f"])
DNBR_CHANNEL, DNBR_SCALE = 18, 2.0

plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})


def label_rule(x: np.ndarray, y: np.ndarray) -> None:
    dnbr = x[:, DNBR_CHANNEL].astype(np.float32) / DNBR_SCALE
    valid = y != 255
    figure, axes = plt.subplots(1, 2, figsize=(11, 3.8))
    bins = np.linspace(-0.1, 0.9, 101)
    for cls, color, name in ((1, "#e0b21a", "слабая"), (2, "#ee8a35", "средняя"), (3, "#d2382f", "сильная")):
        axes[0].hist(dnbr[valid & (y == cls)], bins=bins, color=color, alpha=0.75, label=name)
    axes[0].axvline(0.06, color="black", lw=1, ls="--")
    axes[0].set(xlabel="dNBR", ylabel="пикселей", title="Гари нет при dNBR ниже 0,06")
    axes[0].legend(frameon=False)

    rows, cols = np.mgrid[0:512, 0:512]
    dist = np.hypot(rows - 255.5, cols - 255.5)
    edges = np.arange(0, 380, 30)
    high = valid & (dnbr > 0.1)
    share = [
        ((y > 0) & high)[:, (dist >= lo) & (dist < lo + 30)].sum()
        / max(high[:, (dist >= lo) & (dist < lo + 30)].sum(), 1)
        for lo in edges
    ]
    axes[1].bar(edges + 15, share, width=26, color=ACCENT)
    axes[1].set(
        xlabel="расстояние до центра чипа, пикселей",
        ylabel="доля гари среди dNBR > 0,1",
        title="У края чипа высокий dNBR чаще не гарь",
    )
    figure.tight_layout()
    figure.savefig(FIGURES / "fig1_label_rule.png", dpi=110)
    plt.close(figure)


def ladder(steps: list[tuple[str, float, float]]) -> None:
    figure, axis = plt.subplots(figsize=(9, 0.55 * len(steps) + 1.4))
    names = [s[0] for s in steps][::-1]
    burn, sev = [s[1] for s in steps][::-1], [s[2] for s in steps][::-1]
    positions = np.arange(len(steps))
    axis.barh(positions + 0.2, burn, height=0.38, color=ACCENT, label="IoU гари")
    axis.barh(positions - 0.2, sev, height=0.38, color=FIRE, label="mIoU степеней")
    for pos, b, s in zip(positions, burn, sev, strict=True):
        axis.text(b + 0.005, pos + 0.2, f"{b:.3f}", va="center")
        axis.text(s + 0.005, pos - 0.2, f"{s:.3f}", va="center")
    axis.set_yticks(positions, names)
    axis.set(
        xlim=(0, 0.95),
        xlabel="OOF, GroupKFold по событиям пожара",
        title="Основной прирост дают контекст сети и обучаемое смешивание",
    )
    axis.legend(frameon=False, loc="upper right")
    figure.tight_layout()
    figure.savefig(FIGURES / "fig2_ladder.png", dpi=110)
    plt.close(figure)


def examples(x: np.ndarray, y: np.ndarray, tags: list[str], chips: list[int]) -> None:
    oof = np.mean(
        [np.load(OUT / f"oof_cnn_{tag}.npy", mmap_mode="r")[chips].astype(np.float32) for tag in tags], axis=0
    )
    figure, axes = plt.subplots(len(chips), 4, figsize=(14, 3.5 * len(chips)))
    for row, index, proba in zip(axes, chips, oof, strict=True):
        post = x[index, 9:18].astype(np.float32) / 3.0
        rgb = np.clip(
            np.stack([post[8], post[6], post[2]], axis=-1) / np.percentile(post[[8, 6, 2]], 99), 0, 1
        )
        truth, pred = np.where(y[index] == 255, 0, y[index]), proba.argmax(0)
        row[0].imshow(rgb)
        row[0].set_title("после пожара, B12-B8A-B4")
        row[1].imshow(
            x[index, DNBR_CHANNEL].astype(np.float32) / DNBR_SCALE, cmap="RdYlBu_r", vmin=-0.3, vmax=0.8
        )
        row[1].set_title("dNBR")
        row[2].imshow(truth, cmap=SEVERITY, vmin=0, vmax=3, interpolation="nearest")
        row[2].set_title("эталон")
        row[3].imshow(pred, cmap=SEVERITY, vmin=0, vmax=3, interpolation="nearest")
        row[3].set_title("сеть, прогноз вне обучения")
        for axis in row:
            axis.axis("off")
    figure.tight_layout()
    figure.savefig(FIGURES / "fig3_examples.png", dpi=75)
    plt.close(figure)


def importance(stack_file: Path) -> None:
    gain = json.loads(stack_file.read_text(encoding="utf-8"))["importance_gain"]
    names, values = list(gain)[:14][::-1], list(gain.values())[:14][::-1]
    figure, axis = plt.subplots(figsize=(8, 4.6))
    axis.barh(
        names,
        values,
        color=[ACCENT if n.startswith("gbm") else FIRE if n.startswith("unet") else OTHER for n in names],
    )
    axis.set(xlabel="доля суммарного gain", title="Второй уровень: степени берёт у бустинга, контур у сетей")
    figure.tight_layout()
    figure.savefig(FIGURES / "fig4_stack_importance.png", dpi=110)
    plt.close(figure)


def main() -> None:
    tags = sys.argv[1:]
    FIGURES.mkdir(parents=True, exist_ok=True)
    data = np.load(OUT / "cnn_cache.npz")
    x, y = data["x"], data["y"]
    label_rule(x, y)
    steps = json.loads((OUT / "ladder.json").read_text(encoding="utf-8"))
    ladder([(s["name"], s["iou_burn"], s["miou_sev"]) for s in steps])
    examples(x, y, [part for tag in tags for part in tag.split("+")], [105, 109, 151, 220])
    importance(OUT / f"stack_{'+'.join(tags)}.json")


if __name__ == "__main__":
    main()
