"""Проверка гипотезы: внутри гари степень задана порогами одного индекса. Точность лучшей пары порогов."""

from __future__ import annotations

import json

import numpy as np
from sklearn.tree import DecisionTreeClassifier

from experiments import OUT

CANDIDATES = (
    "d_nbr",
    "rbr",
    "rdnbr",
    "d_nbr_offset",
    "post_nbr",
    "d_ndvi",
    "d_nbr_mean_5",
    "d_nbr2",
    "d_ndmi",
    "post_mirbi",
)


def main() -> None:
    names = json.loads((OUT / "pixels_features.json").read_text(encoding="utf-8"))
    y = np.load(OUT / "pixels_y.npy")
    burned = np.flatnonzero(y > 0)
    x = np.load(OUT / "pixels_x.npy", mmap_mode="r")
    block = np.asarray(x[burned])
    target = y[burned]
    print(
        "burned pixels",
        len(target),
        "majority share",
        round(float(np.bincount(target).max() / len(target)), 4),
    )
    for name in CANDIDATES:
        column = block[:, [names.index(name)]]
        tree = DecisionTreeClassifier(max_leaf_nodes=3, random_state=0).fit(column, target)
        thresholds = sorted(t for t in tree.tree_.threshold if t != -2)
        print(
            f"{name:>14}: accuracy {tree.score(column, target):.4f} thresholds {[round(float(t), 4) for t in thresholds]}"
        )
    pair = block[:, [names.index("d_nbr"), names.index("pre_nbr"), names.index("landcover")]]
    tree = DecisionTreeClassifier(max_leaf_nodes=24, random_state=0).fit(pair, target)
    print("d_nbr + pre_nbr + landcover, 24 leaves:", round(tree.score(pair, target), 4))


if __name__ == "__main__":
    main()
