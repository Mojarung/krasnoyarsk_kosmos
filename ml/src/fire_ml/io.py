from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio

from fire_ml.contract import AfChip, BsChip

AF_FILES = {"viirs": "viirs/{id}_VIIRS_I1-I5.tif", "aux": "aux/{id}_AUX.tif", "mask": "masks/{id}_MASK.tif"}
BS_FILES = {
    "s2_pre": "sentinel2_pre/{id}_Sentinel-2_pre.tif",
    "s2_post": "sentinel2_post/{id}_Sentinel-2_post.tif",
    "s1_pre": "sentinel1_pre/{id}_Sentinel-1_pre.tif",
    "s1_post": "sentinel1_post/{id}_Sentinel-1_post.tif",
    "aux": "aux/{id}_AUX.tif",
    "mask": "masks/{id}_MASK.tif",
}

# Выданный набор кладёт вспомогательный растр в aux/, ранние сборки — в _aux/.
# Держим оба: берём тот каталог, который реально есть на диске. Без этого сид
# пропускал все 644 чипа с сообщением «нет файлов ['aux']», хотя файлы лежали рядом.
AUX_DIRS = ("aux", "_aux")


def read_raster(path: str | Path) -> np.ndarray:
    with rasterio.open(path) as ds:
        return ds.read()


def _aux_path(kind_dir: Path, chip_id: str) -> Path:
    candidates = [kind_dir / name / f"{chip_id}_AUX.tif" for name in AUX_DIRS]
    return next((path for path in candidates if path.exists()), candidates[0])


def chip_paths(kind_dir: str | Path, chip_id: str, kind: str) -> dict[str, Path]:
    layout = AF_FILES if kind == "af" else BS_FILES
    root = Path(kind_dir)
    paths = {role: root / pattern.format(id=chip_id) for role, pattern in layout.items()}
    paths["aux"] = _aux_path(root, chip_id)
    return paths


def load_af_chip(chip_id: str, paths: dict[str, Path]) -> AfChip:
    return AfChip(chip_id=chip_id, viirs=read_raster(paths["viirs"]), aux=read_raster(paths["aux"]))


def load_bs_chip(chip_id: str, paths: dict[str, Path]) -> BsChip:
    return BsChip(
        chip_id=chip_id,
        s2_pre=read_raster(paths["s2_pre"]),
        s2_post=read_raster(paths["s2_post"]),
        s1_pre=read_raster(paths["s1_pre"]),
        s1_post=read_raster(paths["s1_post"]),
        aux=read_raster(paths["aux"]),
    )
