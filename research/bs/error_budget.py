"""Разложение ошибки итогового стекинга: сколько теряем на контуре, сколько на степенях и в каких чипах."""

from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from experiments import BS, OUT, case_metrics


def main() -> None:
    tag = sys.argv[1]
    names = json.loads((OUT / "pixels_features.json").read_text(encoding="utf-8"))
    y = np.load(OUT / "pixels_y.npy").astype(np.int64)
    chip = np.load(OUT / "pixels_chip.npy")
    x = np.load(OUT / "pixels_x.npy", mmap_mode="r")
    dnbr, lc = np.asarray(x[:, names.index("d_nbr")]), np.asarray(x[:, names.index("landcover")])
    proba = np.load(OUT / f"oof_stack_{tag}.npy")
    pred = (proba * np.array([1.0, 1.8, 1.8, 1.8])).argmax(1)
    print("текущее:", case_metrics(y, pred))

    tp = (y > 0) & (pred > 0)
    print(f"\nстепень внутри верно найденной гари: точность {(y[tp] == pred[tp]).mean():.4f}")
    oracle_sev = np.where(pred > 0, np.where(y > 0, y, pred), 0)
    print("если бы степень была идеальной при нашем контуре:", case_metrics(y, oracle_sev))
    rule = np.where(dnbr >= 0.386, 3, np.where(dnbr >= 0.185, 2, 1))
    print("наш контур + степень порогами dNBR:", case_metrics(y, np.where(pred > 0, rule, 0)))
    oracle_burn = np.where(y > 0, np.where(pred > 0, pred, rule), 0)
    print("если бы контур был идеальным, степень наша:", case_metrics(y, oracle_burn))

    fp, fn = (pred > 0) & (y == 0), (pred == 0) & (y > 0)
    print(f"\nошибки контура: ложная гарь {fp.sum()}, пропуск {fn.sum()}, верно {tp.sum()}")
    for name, mask in (("ложная гарь", fp), ("пропуск", fn)):
        bands = pd.cut(
            dnbr[mask], [-9, 0.1, 0.185, 0.386, 9], labels=["<0.10", "0.10-0.185", "0.185-0.386", ">0.386"]
        )
        print(f"  {name} по dNBR:", pd.Series(bands).value_counts(normalize=True).round(3).to_dict())
        print(
            f"  {name} по покрову:",
            pd.Series(lc[mask]).value_counts(normalize=True).round(3).head(4).to_dict(),
        )

    meta = pd.read_csv(BS / "meta.csv")
    frame = pd.DataFrame({"chip": chip, "fp": fp, "fn": fn, "tp": tp})
    per = frame.groupby("chip")[["fp", "fn", "tp"]].sum()
    per["err"] = per.fp + per.fn
    per["iou"] = per.tp / (per.tp + per.err).clip(lower=1)
    per = per.sort_values("err", ascending=False)
    print(
        f"\n10 худших чипов дают {per.err.head(10).sum() / per.err.sum():.1%} всех ошибок контура, 30 худших {per.err.head(30).sum() / per.err.sum():.1%}"
    )
    top = per.head(12).assign(
        chip_id=meta.chip_id.to_numpy()[per.head(12).index],
        lc_top=meta.landcover_top.to_numpy()[per.head(12).index],
    )
    print(top[["chip_id", "fp", "fn", "tp", "iou"]].to_string())


if __name__ == "__main__":
    main()
