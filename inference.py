"""Инференс обоих модулей и сборка submission.csv.

    python inference.py --data-dir /path/to/test --output /path/to/submission.csv

Каталог данных имеет структуру выданного набора: sample_submission.csv, af/, bs/.
Модели берутся из реестра fire_ml (переменные FIRE_ML_AF, FIRE_ML_BS), по умолчанию боевые.
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from fire_ml import load_af_model, load_bs_model
from fire_ml.io import chip_paths, load_af_chip, load_bs_chip
from fire_ml.rle import encode

log = logging.getLogger("inference")
MAX_WORKERS = 8
SEVERITY_CLASSES = (1, 2, 3)
AUX_FALLBACKS = ("_aux", "aux")

_models: dict[str, object] = {}


def _init_worker() -> None:
    _models["af"] = load_af_model()
    _models["bs"] = load_bs_model()


def _resolve(kind_dir: Path, chip_id: str, kind: str) -> dict[str, Path]:
    paths = chip_paths(kind_dir, chip_id, kind)
    if not paths["aux"].exists():
        for folder in AUX_FALLBACKS:
            candidate = kind_dir / folder / paths["aux"].name
            if candidate.exists():
                paths["aux"] = candidate
                break
    return paths


def _predict(task: tuple[str, str, str]) -> tuple[str, dict[int, str]]:
    chip_id, kind, data_dir = task
    paths = _resolve(Path(data_dir) / kind, chip_id, kind)
    try:
        if kind == "af":
            mask = _models["af"].predict(load_af_chip(chip_id, paths)).fire_mask
            return chip_id, {1: encode(mask == 1)}
        severity = _models["bs"].predict(load_bs_chip(chip_id, paths)).severity
        return chip_id, {k: encode(severity == k) for k in SEVERITY_CLASSES}
    except Exception:
        log.exception("Чип %s не обработан, в сабмит уходит пустая маска", chip_id)
        return chip_id, {k: "" for k in ((1,) if kind == "af" else SEVERITY_CLASSES)}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=min(MAX_WORKERS, os.cpu_count() or 1))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)

    started = time.perf_counter()
    with (args.data_dir / "sample_submission.csv").open(encoding="utf-8", newline="") as handle:
        template = [(row["chip_id"], int(row["class_id"])) for row in csv.DictReader(handle)]
    chips = sorted({chip_id for chip_id, _ in template})
    tasks = [(chip_id, "af" if chip_id.startswith("AF") else "bs", str(args.data_dir)) for chip_id in chips]

    with ProcessPoolExecutor(max_workers=max(args.workers, 1), initializer=_init_worker) as pool:
        predictions = dict(pool.map(_predict, tasks, chunksize=4))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    lines = ["chip_id,class_id,rle"]
    lines += [
        f'{chip_id},{class_id},"{predictions[chip_id].get(class_id, "")}"' for chip_id, class_id in template
    ]
    args.output.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))

    non_empty = sum(1 for chip_id, class_id in template if predictions[chip_id].get(class_id))
    log.info(
        "Готово: %s строк, непустых %s, %.1f с, файл %s",
        len(template),
        non_empty,
        time.perf_counter() - started,
        args.output,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
