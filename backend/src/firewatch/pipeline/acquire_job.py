from __future__ import annotations

import asyncio
import logging
import tempfile
import uuid
from datetime import date
from pathlib import Path

import httpx
from affine import Affine
from rasterio.errors import RasterioError
from sqlalchemy import update

from firewatch.config import get_settings
from firewatch.db.models import Scene
from firewatch.db.session import SessionFactory
from firewatch.infra import s3
from firewatch.infra.stac import NoImageryError
from firewatch.pipeline.acquire import GSD_M, AcquiredChip, ChipGrid, assemble_chip
from firewatch.pipeline.ingest import process_scene, report
from firewatch.services.scenes import raw_key

log = logging.getLogger(__name__)

NETWORK_FAILURE = "Каталог снимков недоступен с этого сервера. Проверьте сеть или загрузите чип файлами"


def _upload(scene_id: str, chip: AcquiredChip) -> dict[str, str]:
    files = {}
    for role, path in chip.paths.items():
        files[role] = raw_key("bs", scene_id, role)
        s3.upload_file(path, files[role])
    return files


async def _fail(job_id: uuid.UUID, scene_id: str, message: str) -> None:
    async with SessionFactory() as session:
        await session.execute(update(Scene).where(Scene.id == scene_id).values(status="failed"))
        await session.commit()
    await report(job_id, scene_id, "failed", status="failed", error=message)


async def acquire_scene(job_id: uuid.UUID, scene_id: str) -> None:
    settings = get_settings()
    async with SessionFactory() as session:
        scene = await session.get(Scene, scene_id)
        if scene is None:
            log.error("Сцена %s не найдена, задание на скачивание пропущено", scene_id)
            return
        request = scene.stats["acquisition"]
    origin_x, origin_y = request["origin"]
    grid = ChipGrid(epsg=request["epsg"], transform=Affine(GSD_M, 0.0, origin_x, 0.0, -GSD_M, origin_y))
    date_pre, date_post = (date.fromisoformat(value) for value in request["requested"])

    await report(job_id, scene_id, "acquire")
    try:
        with tempfile.TemporaryDirectory(prefix="fw_live_") as tmp:
            grid, chip = await asyncio.to_thread(
                assemble_chip,
                grid,
                date_pre,
                date_post,
                Path(tmp),
                days=settings.live_search_days,
                candidates=settings.live_candidates,
                fire_context=request if request.get("origin_event") else None,
            )
            files = await asyncio.to_thread(_upload, scene_id, chip)
    except NoImageryError as exc:
        await _fail(job_id, scene_id, str(exc))
        return
    except (httpx.HTTPError, RasterioError):
        log.exception("Не удалось собрать чип %s", scene_id)
        await _fail(job_id, scene_id, NETWORK_FAILURE)
        return

    west, _, _, north = grid.bounds
    async with SessionFactory() as session:
        await session.execute(
            update(Scene)
            .where(Scene.id == scene_id)
            .values(
                files=files,
                date_pre=chip.date_pre,
                date_post=chip.date_post,
                cloud_frac=round(chip.cloud_frac, 4),
                valid_frac=round(chip.valid_frac, 4),
                stats={"acquisition": request | chip.provenance | {"origin": [west, north]}},
            )
        )
        await session.commit()
    await process_scene(job_id, scene_id)
