"""Проверяет submission.csv по правилам постановки кейса.

    python validate_submission.py --submission submission.csv --template DATA/test/sample_submission.csv

Код возврата 0, если файл валиден. Проверяется то же, что перечислено в критерии «Корректность инференса»:
набор пар (chip_id, class_id), декодируемость RLE, границы чипа, порядок и несоприкосновение серий,
отсутствие пересечений классов внутри BS-чипа, отсутствие NaN.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

CHIP_PIXELS = {"AF": 256 * 256, "BS": 512 * 512}
csv.field_size_limit(2**31 - 1)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def check_rle(rle: str, size: int) -> tuple[str | None, np.ndarray]:
    mask = np.zeros(size, dtype=bool)
    if rle == "":
        return None, mask
    try:
        values = np.array(rle.split(), dtype=np.int64)
    except ValueError:
        return "нечисловые значения", mask
    if len(values) % 2:
        return "нечётное число значений", mask
    starts, lengths = values[::2], values[1::2]
    if starts[0] < 1 or (lengths < 1).any():
        return "начало меньше 1 или неположительная длина", mask
    if (starts + lengths - 1).max() > size:
        return "выход за пределы чипа", mask
    if (starts[1:] <= starts[:-1] + lengths[:-1]).any():
        return "серии не по возрастанию, пересекаются или соприкасаются", mask
    edges = np.zeros(size + 1, dtype=np.int8)
    np.add.at(edges, starts - 1, 1)
    np.add.at(edges, starts - 1 + lengths, -1)
    return None, np.cumsum(edges[:-1]) > 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    args = parser.parse_args()

    rows, template = read_rows(args.submission), read_rows(args.template)
    errors: list[str] = []
    if rows and set(rows[0]) != {"chip_id", "class_id", "rle"}:
        errors.append(f"колонки {sorted(rows[0])}, ожидаются chip_id, class_id, rle")

    got = {(r["chip_id"], r["class_id"]) for r in rows}
    expected = {(r["chip_id"], r["class_id"]) for r in template}
    if len(rows) != len(got):
        errors.append("есть повторяющиеся пары (chip_id, class_id)")
    if got != expected:
        errors.append(
            f"пары не совпадают с шаблоном: лишних {len(got - expected)}, не хватает {len(expected - got)}"
        )

    by_chip: dict[str, list[np.ndarray]] = defaultdict(list)
    for row in rows:
        if row["rle"] is None or row["rle"].strip().lower() == "nan":
            errors.append(f"{row['chip_id']} класс {row['class_id']}: NaN вместо пустой строки")
            continue
        problem, mask = check_rle(row["rle"].strip(), CHIP_PIXELS[row["chip_id"][:2]])
        if problem:
            errors.append(f"{row['chip_id']} класс {row['class_id']}: {problem}")
        by_chip[row["chip_id"]].append(mask)

    for chip_id, masks in by_chip.items():
        if len(masks) > 1 and (np.sum(masks, axis=0) > 1).any():
            errors.append(f"{chip_id}: маски классов пересекаются")

    for message in errors[:20]:
        print("ОШИБКА:", message)
    non_empty = sum(1 for r in rows if r["rle"])
    print(f"строк {len(rows)}, непустых {non_empty}, ошибок {len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
