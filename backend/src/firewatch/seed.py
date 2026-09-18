"""Загружает выданный набор чипов в S3 и ставит сцены в очередь обработки.

Запуск: uv run python -m firewatch.seed
Повторный запуск безопасен: готовые сцены и уже загруженные файлы пропускаются.
"""

from __future__ import annotations

import asyncio
import csv
import logging
from datetime import date, datetime
from itertools import zip_longest
from pathlib import Path
from typing import Any

from sqlalchemy import select

from fire_ml.io import chip_paths
from firewatch.config import get_settings
from firewatch.db.models import Scene
from firewatch.db.session import SessionFactory
from firewatch.infra import s3
from firewatch.infra.broker import broker
from firewatch.services.scenes import OPTIONAL_ROLES, raw_key, register_scene, required_roles

log = logging.getLogger("firewatch.seed")


def _text(value: str) -> str | None:
    return None if value in ("", "nan") else value


def _date(value: str) -> date | None:
    return date.fromisoformat(value) if _text(value) else None


def _float(value: str) -> float | None:
    return float(value) if _text(value) else None


def _rows(kind_dir: Path, limit: int) -> list[dict[str, str]]:
    meta = kind_dir / "meta.csv"
    if not meta.exists():
        return []
    with meta.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return rows[:limit] if limit > 0 else rows


def _scene_values(row: dict[str, str], files: dict[str, str]) -> dict[str, Any]:
    acquired = _text(row.get("acq_datetime", ""))
    return {
        "id": row["chip_id"],
        "kind": row["kind"],
        "source": "seed",
        "acquired_at": datetime.fromisoformat(acquired) if acquired else None,
        "satellite": _text(row.get("satellite", "")),
        "date_pre": _date(row.get("date_pre", "")),
        "date_post": _date(row.get("date_post", "")),
        "s1_date_pre": _date(row.get("s1_date_pre", "")),
        "s1_date_post": _date(row.get("s1_date_post", "")),
        "fire_event_id": _text(row.get("fire_event_id", "")),
        "valid_frac": _float(row.get("valid_frac", "")),
        "cloud_frac": _float(row.get("cloud_frac", "")),
        "files": files,
    }


def _upload(kind_dir: Path, row: dict[str, str]) -> dict[str, str] | None:
    kind, chip_id = row["kind"], row["chip_id"]
    paths = chip_paths(kind_dir, chip_id, kind)
    missing = [role for role in required_roles(kind) if not paths[role].exists()]
    if missing:
        log.warning("%s пропущен: нет файлов %s", chip_id, missing)
        return None
    files = {}
    for role in (*required_roles(kind), *OPTIONAL_ROLES):
        if not paths[role].exists():
            continue
        files[role] = raw_key(kind, chip_id, role)
        if not s3.exists(files[role]):
            s3.upload_file(paths[role], files[role])
    return files


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    data_dir = settings.data_dir
    if not data_dir.exists():
        log.warning(
            "Каталог с данными %s не найден. Сервис запустится пустым, сцены можно загрузить через API.",
            data_dir,
        )
        return

    s3.ensure_bucket()
    af = [(data_dir / "af", row) for row in _rows(data_dir / "af", settings.seed_limit_af)]
    bs = [(data_dir / "bs", row) for row in _rows(data_dir / "bs", settings.seed_limit_bs)]
    interleaved = [item for pair in zip_longest(bs, af) for item in pair if item is not None]

    async with SessionFactory() as session:
        ready = set(
            (
                await session.execute(
                    select(Scene.id).where(Scene.status.in_(("ready", "queued", "processing")))
                )
            ).scalars()
        )

    queued = 0
    async with broker:
        for kind_dir, row in interleaved:
            if row["chip_id"] in ready:
                continue
            files = await asyncio.to_thread(_upload, kind_dir, row)
            if files is None:
                continue
            async with SessionFactory() as session:
                await register_scene(session, _scene_values(row, files))
            queued += 1
            if queued % 50 == 0:
                log.info("В очереди %s сцен", queued)
    log.info("Готово: поставлено в очередь %s сцен, пропущено %s", queued, len(interleaved) - queued)


if __name__ == "__main__":
    asyncio.run(main())
