from __future__ import annotations

import asyncio
import logging
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from geoalchemy2.shape import from_shape
from sqlalchemy import delete, insert, update
from sqlalchemy.ext.asyncio import AsyncSession

from fire_ml import load_af_model, load_bs_model
from firewatch.config import get_settings
from firewatch.db.models import BurnArea, Hotspot, Job, ScarLandcover, Scene, SeverityPolygon
from firewatch.db.session import SessionFactory
from firewatch.infra import s3
from firewatch.infra.cache import bump_data_version, publish_event
from firewatch.pipeline.alerts import deliver_alerts, raise_zone_alerts
from firewatch.pipeline.compute import AfResult, BsResult, compute_af, compute_bs
from firewatch.pipeline.georef import WGS84, GeoRef
from firewatch.pipeline.persistence import mark_dirty, refresh_persistent_sources

log = logging.getLogger(__name__)

STAGES = ("queued", "acquire", "fetch", "inference", "previews", "publish", "done")
STAGE_MESSAGES = {
    "acquire": "Ищем и скачиваем снимки Sentinel-2 по выбранной области",
    "fetch": "Забираем растры из S3",
    "inference": "Модель размечает пиксели, маски становятся контурами с площадью в UTM",
    "previews": "Сохраняем превью «до/после» в S3",
    "publish": "Пишем в PostGIS, проверяем зоны наблюдения",
    "done": "Сцена на карте",
}
INSERT_CHUNK = 2000

_af_model = load_af_model()
_bs_model = load_bs_model()


# Статистика сцены переписывается при каждой обработке. Эти ключи описывают происхождение данных и переживают её.
PRESERVED_STATS = ("acquisition",)


async def report(
    job_id: uuid.UUID,
    scene_id: str,
    stage: str,
    *,
    status: str = "running",
    error: str | None = None,
    message: str | None = None,
) -> None:
    progress = STAGES.index(stage) / (len(STAGES) - 1) if stage in STAGES else 0.0
    message = error or message or STAGE_MESSAGES.get(stage, "")
    async with SessionFactory() as session:
        await session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(status=status, stage=stage, progress=progress, message=message, error=error)
        )
        await session.commit()
    await publish_event(
        "job",
        {
            "id": str(job_id),
            "scene_id": scene_id,
            "status": status,
            "stage": stage,
            "progress": progress,
            "message": message,
        },
    )


def _download(files: dict[str, str], target: Path) -> dict[str, Path]:
    paths = {}
    for role, key in files.items():
        paths[role] = target / f"{role}.tif"
        s3.download_file(key, paths[role])
    return paths


def _upload_quicklooks(scene_id: str, looks: dict[str, bytes]) -> dict[str, str]:
    keys = {}
    for name, body in looks.items():
        keys[name] = f"quicklooks/{scene_id}/{name}.webp"
        s3.put_bytes(keys[name], body, "image/webp")
    return keys


def _scene_geometry(georef: GeoRef) -> dict[str, Any]:
    return {
        "epsg": georef.epsg,
        "footprint": from_shape(georef.to_wgs84(georef.footprint_utm()), srid=WGS84),
        "corners": georef.corners_wgs84(),
        "width": georef.width,
        "height": georef.height,
        "gsd": georef.gsd,
    }


async def _bulk_insert(session: AsyncSession, model: type, rows: list[dict[str, Any]]) -> None:
    for start in range(0, len(rows), INSERT_CHUNK):
        await session.execute(insert(model), rows[start : start + INSERT_CHUNK])


async def _publish_af(session: AsyncSession, scene: Scene, result: AfResult) -> None:
    await session.execute(delete(Hotspot).where(Hotspot.scene_id == scene.id))
    rows = [
        {
            **{k: v for k, v in h.items() if k not in {"lon", "lat"}},
            "scene_id": scene.id,
            "geom": f"SRID=4326;POINT({h['lon']} {h['lat']})",
            "epsg": result.georef.epsg,
            "acquired_at": scene.acquired_at,
            "satellite": scene.satellite,
            "persistent": False,
        }
        for h in result.hotspots
    ]
    await _bulk_insert(session, Hotspot, rows)


async def _publish_bs(session: AsyncSession, scene: Scene, result: BsResult) -> None:
    await session.execute(delete(BurnArea).where(BurnArea.scene_id == scene.id))
    await session.execute(delete(ScarLandcover).where(ScarLandcover.scene_id == scene.id))
    georef = result.georef
    area_ids: dict[int, int] = {}
    for burn in result.burn_shapes:
        area = BurnArea(
            scene_id=scene.id,
            fire_event_id=scene.fire_event_id,
            geom=from_shape(georef.to_wgs84(burn.geom_utm), srid=WGS84),
            epsg=georef.epsg,
            area_ha=burn.area_ha,
            sev1_ha=burn.severity_ha[0],
            sev2_ha=burn.severity_ha[1],
            sev3_ha=burn.severity_ha[2],
            date_pre=scene.date_pre,
            date_post=scene.date_post,
        )
        session.add(area)
        await session.flush()
        area_ids[burn.label] = area.id

    await _bulk_insert(
        session,
        SeverityPolygon,
        [
            {
                "scene_id": scene.id,
                "burn_area_id": area_ids[shape.burn_label],
                "severity": shape.severity,
                "geom": from_shape(georef.to_wgs84(shape.geom_utm), srid=WGS84),
                "epsg": georef.epsg,
                "area_ha": shape.area_ha,
                "date_post": scene.date_post,
            }
            for shape in result.severity_shapes
        ],
    )
    await _bulk_insert(
        session,
        ScarLandcover,
        [
            {"scene_id": scene.id, "severity": severity, "lc_group": group, "area_ha": area_ha}
            for (severity, group), area_ha in result.landcover_ha.items()
        ],
    )


def _validate_dates(scene: Scene) -> None:
    if scene.kind == "af" and scene.acquired_at is None:
        raise ValueError("Для AF-сцены нужен момент пролёта (acq_datetime)")
    if scene.kind == "bs" and (scene.date_pre is None or scene.date_post is None):
        raise ValueError("Для BS-сцены нужны даты съёмки «до» и «после»")


async def process_scene(job_id: uuid.UUID, scene_id: str) -> None:
    try:
        await _process(job_id, scene_id)
    except Exception as exc:
        log.exception("Сцена %s не обработана", scene_id)
        async with SessionFactory() as session:
            await session.execute(update(Scene).where(Scene.id == scene_id).values(status="failed"))
            await session.commit()
        await report(job_id, scene_id, "failed", status="failed", error=str(exc))


async def _process(job_id: uuid.UUID, scene_id: str) -> None:
    settings = get_settings()
    started = time.perf_counter()
    async with SessionFactory() as session:
        scene = await session.get(Scene, scene_id)
        if scene is None:
            raise LookupError(f"Сцена {scene_id} не найдена")
        _validate_dates(scene)
        scene.status = "processing"
        await session.commit()

    with tempfile.TemporaryDirectory(prefix="fw_") as tmp:
        await report(job_id, scene_id, "fetch")
        paths = await asyncio.to_thread(_download, scene.files, Path(tmp))

        await report(job_id, scene_id, "inference")
        if scene.kind == "af":
            result: AfResult | BsResult = await asyncio.to_thread(compute_af, scene_id, paths, _af_model)
        else:
            result = await asyncio.to_thread(compute_bs, scene_id, paths, _bs_model, settings.min_polygon_px)

    await report(job_id, scene_id, "previews")
    quicklooks = await asyncio.to_thread(_upload_quicklooks, scene_id, result.quicklooks)

    await report(job_id, scene_id, "publish")
    async with SessionFactory() as session:
        scene = await session.get(Scene, scene_id)
        assert scene is not None
        for key, value in _scene_geometry(result.georef).items():
            setattr(scene, key, value)
        scene.model_name = result.model_name
        preserved = {key: scene.stats[key] for key in PRESERVED_STATS if key in (scene.stats or {})}
        scene.stats = (
            preserved | result.stats | {"duration_ms": round((time.perf_counter() - started) * 1000)}
        )
        scene.quicklooks = quicklooks
        scene.status = "ready"
        scene.processed_at = datetime.now(UTC)
        if isinstance(result, AfResult):
            await _publish_af(session, scene, result)
        else:
            await _publish_bs(session, scene, result)
        await session.commit()

    alerts = []
    if isinstance(result, AfResult):
        await mark_dirty()
        async with SessionFactory() as session:
            await refresh_persistent_sources(session)
            alerts = await raise_zone_alerts(session, scene_id)
            await session.commit()

    await bump_data_version()
    await deliver_alerts(alerts)
    await report(job_id, scene_id, "done", status="done")
    await publish_event(
        "scene", {"id": scene_id, "kind": scene.kind, "status": "ready", "stats": result.stats}
    )
