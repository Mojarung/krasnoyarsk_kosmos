"""Перенос обученных сетей в пакет fire_ml: веса в fp16 и описание групп сетей для ансамбля.

Запуск: python research/bs/export.py <tag>:<arch>:<encoder> [<tag>:<arch>:<encoder> ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import torch

RESULTS = Path("research/bs/results")
SOURCE = Path("research/bs/weights")
TARGET = Path("ml/src/fire_ml/weights")


def main() -> None:
    groups = [dict(zip(("tag", "arch", "encoder"), spec.split(":"), strict=True)) for spec in sys.argv[1:]]
    for old in [*TARGET.glob("bs_net_*.pt"), *TARGET.glob("bs_unet_*.pt")]:
        old.unlink()
    for group in groups:
        for path in sorted(SOURCE.glob(f"{group['tag']}_fold*.pt")):
            state = {
                k: (v.half() if v.is_floating_point() else v)
                for k, v in torch.load(path, map_location="cpu").items()
            }
            target = TARGET / f"bs_net_{path.stem}.pt"
            torch.save(state, target)
            print(target.name, target.stat().st_size // 2**20, "MB")
        group["weights_glob"] = f"bs_net_{group['tag']}_fold*.pt"

    gbm = json.loads((RESULTS / "gbm_tuned.json").read_text(encoding="utf-8"))
    config = {"cnn": groups, "gbm_only": gbm}
    (TARGET / "bs_blend.json").write_text(json.dumps(config, indent=1), encoding="utf-8")
    print(json.dumps(config, indent=1))


if __name__ == "__main__":
    main()
