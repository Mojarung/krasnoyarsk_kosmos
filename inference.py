"""Инференс обоих модулей и сборка submission.csv.

    python inference.py --data-dir /path/to/test --output /path/to/submission.csv

Каталог данных имеет структуру выданного набора: sample_submission.csv, af/, bs/.
Модели берутся из реестра fire_ml (переменные FIRE_ML_AF, FIRE_ML_BS), по умолчанию боевые.

Видеокарту держит один процесс, главный: он считает сегментационные сети пачками и складывает вероятности
во временный каталог. Процессы пула делают всё остальное на CPU (признаки, бустинги, RLE) и torch не
импортируют: восемь копий сетей в памяти видеокарты не нужны, а запуск пула не ждёт загрузки CUDA.
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import tempfile
import time
from collections.abc import Iterator
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor
from itertools import islice
from pathlib import Path

import numpy as np

from fire_ml import load_af_model, load_bs_model
from fire_ml.io import chip_paths, load_af_chip, load_bs_chip
from fire_ml.rle import encode

log = logging.getLogger("inference")
MAX_WORKERS = 8
SEVERITY_CLASSES = (1, 2, 3)
AUX_FALLBACKS = ("_aux", "aux")
# Пачка сетей: 4 чипа × 4 отражения помещаются в 6 ГБ памяти видеокарты вместе с пятью фолдами.
NET_BATCH = 4
TENSOR_THREADS = 4
PREFETCH = 12

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


def _predict(task: tuple[str, str, str, str | None]) -> tuple[str, dict[int, str]]:
    chip_id, kind, data_dir, nets_path = task
    paths = _resolve(Path(data_dir) / kind, chip_id, kind)
    try:
        if kind == "af":
            mask = _models["af"].predict(load_af_chip(chip_id, paths)).fire_mask
            return chip_id, {1: encode(mask == 1)}
        chip = load_bs_chip(chip_id, paths)
        if nets_path is None:
            severity = _models["bs"].predict(chip).severity
        else:
            with np.load(nets_path) as nets:
                severity = _models["bs"].predict(chip, nets=dict(nets)).severity
        return chip_id, {k: encode(severity == k) for k in SEVERITY_CLASSES}
    except Exception:
        log.exception("Чип %s не обработан, в сабмит уходит пустая маска", chip_id)
        return chip_id, {k: "" for k in ((1,) if kind == "af" else SEVERITY_CLASSES)}


def _bs_tensor(model: object, data_dir: str, chip_id: str) -> np.ndarray | None:
    try:
        return model.tensors(load_bs_chip(chip_id, _resolve(Path(data_dir) / "bs", chip_id, "bs")))
    except Exception:
        log.exception("Чип %s: вход сетей не собран, чип пойдёт без них", chip_id)
        return None


def _run_nets(
    model: object, pool: ProcessPoolExecutor, bs_chips: list[str], data_dir: str, cache: Path
) -> list[Future]:
    """Сети считаются в главном процессе, и каждый чип уходит в пул сразу, как готовы его вероятности."""
    futures = []
    with ThreadPoolExecutor(TENSOR_THREADS) as threads:
        # Окно упреждения: вход одного чипа весит 69 МБ, весь тест разом занял бы 6 ГБ.
        queue = [threads.submit(_bs_tensor, model, data_dir, chip_id) for chip_id in bs_chips[:PREFETCH]]
        upcoming = iter(bs_chips[PREFETCH:])

        def tensors() -> Iterator[np.ndarray | None]:
            while queue:
                ready = queue.pop(0).result()
                for chip_id in islice(upcoming, 1):
                    queue.append(threads.submit(_bs_tensor, model, data_dir, chip_id))
                yield ready

        pending: list[tuple[str, np.ndarray]] = []

        def flush() -> None:
            if not pending:
                return
            try:
                results = model.cnn_proba(np.stack([tensor for _, tensor in pending]))
            except Exception:
                log.exception("Сети не отработали на пачке %s, чипы пойдут без них", [c for c, _ in pending])
                results = [None] * len(pending)
            for (chip_id, _), nets in zip(pending, results, strict=True):
                path = None
                if nets is not None:
                    path = str(cache / f"{chip_id}.npz")
                    np.savez(path, **nets)
                futures.append(pool.submit(_predict, (chip_id, "bs", data_dir, path)))
            pending.clear()

        for chip_id, tensor in zip(bs_chips, tensors(), strict=True):
            if tensor is None:
                futures.append(pool.submit(_predict, (chip_id, "bs", data_dir, None)))
                continue
            pending.append((chip_id, tensor))
            if len(pending) == NET_BATCH:
                flush()
        flush()
    return futures


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
    af_chips = [chip_id for chip_id in chips if chip_id.startswith("AF")]
    bs_chips = [chip_id for chip_id in chips if not chip_id.startswith("AF")]
    data_dir = str(args.data_dir)

    with (
        tempfile.TemporaryDirectory(prefix="firewatch_nets_") as cache,
        ProcessPoolExecutor(max_workers=max(args.workers, 1), initializer=_init_worker) as pool,
    ):
        futures = [pool.submit(_predict, (chip_id, "af", data_dir, None)) for chip_id in af_chips]
        bs_model = load_bs_model()
        if getattr(bs_model, "has_nets", False):
            futures += _run_nets(bs_model, pool, bs_chips, data_dir, Path(cache))
            log.info("Сети отработали: %s чипов, %.1f с", len(bs_chips), time.perf_counter() - started)
        else:
            futures += [pool.submit(_predict, (chip_id, "bs", data_dir, None)) for chip_id in bs_chips]
        predictions = dict(future.result() for future in futures)

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
