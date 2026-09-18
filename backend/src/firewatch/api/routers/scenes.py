from __future__ import annotations

import asyncio
import re
import tempfile
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Response, UploadFile
from geoalchemy2.shape import to_shape
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from firewatch.api.schemas import parse_bbox
from firewatch.db.models import Job, Scene
from firewatch.db.session import get_session
from firewatch.infra import s3
from firewatch.pipeline.georef import GeoRef, MissingGeoreferenceError
from firewatch.services.scenes import OPTIONAL_ROLES, raw_key, register_scene, required_roles

router = APIRouter(prefix="/api/v1", tags=["Сцены и конвейер"])
Session = Annotated[AsyncSession, Depends(get_session)]

SCENE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-]{3,64}$")
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
QUICKLOOK_CACHE = "public, max-age=86400"
GEOREF_ROLE = {"af": "viirs", "bs": "s2_post"}


def _scene_json(scene: Scene, *, detailed: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": scene.id,
        "kind": scene.kind,
        "status": scene.status,
        "source": scene.source,
        "acquired_at": scene.acquired_at.isoformat() if scene.acquired_at else None,
        "satellite": scene.satellite,
        "date_pre": scene.date_pre.isoformat() if scene.date_pre else None,
        "date_post": scene.date_post.isoformat() if scene.date_post else None,
        "fire_event_id": scene.fire_event_id,
        "cloud_frac": scene.cloud_frac,
        "valid_frac": scene.valid_frac,
        "model_name": scene.model_name,
        "stats": scene.stats,
        "corners": scene.corners,
        "quicklooks": sorted(scene.quicklooks),
    }
    if detailed:
        data |= {
            "epsg": scene.epsg,
            "gsd": scene.gsd,
            "width": scene.width,
            "height": scene.height,
            "s1_date_pre": scene.s1_date_pre.isoformat() if scene.s1_date_pre else None,
            "s1_date_post": scene.s1_date_post.isoformat() if scene.s1_date_post else None,
            "footprint": to_shape(scene.footprint).__geo_interface__ if scene.footprint is not None else None,
        }
    return data


@router.get("/scenes", summary="Каталог сцен")
async def list_scenes(
    session: Session,
    kind: Literal["af", "bs"] | None = None,
    status: str | None = None,
    bbox: str | None = Query(None, description="west,south,east,north"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    statement = select(Scene)
    if kind:
        statement = statement.where(Scene.kind == kind)
    if status:
        statement = statement.where(Scene.status == status)
    if bbox:
        statement = statement.where(
            func.ST_Intersects(Scene.footprint, func.ST_MakeEnvelope(*parse_bbox(bbox), 4326))
        )
    total = (await session.execute(select(func.count()).select_from(statement.subquery()))).scalar_one()
    order = func.coalesce(Scene.date_post, func.date(Scene.acquired_at)).desc().nulls_last()
    scenes = (
        await session.execute(statement.order_by(order, Scene.id).limit(limit).offset(offset))
    ).scalars()
    return {"total": total, "items": [_scene_json(s) for s in scenes]}


async def _get_scene(session: AsyncSession, scene_id: str) -> Scene:
    scene = await session.get(Scene, scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail=f"Сцена {scene_id} не найдена")
    return scene


@router.get("/scenes/{scene_id}", summary="Карточка сцены")
async def get_scene(scene_id: str, session: Session) -> dict[str, Any]:
    return _scene_json(await _get_scene(session, scene_id), detailed=True)


@router.get("/scenes/{scene_id}/quicklooks/{name}", summary="Превью сцены (WebP) из S3")
async def get_quicklook(scene_id: str, name: str, session: Session) -> Response:
    scene = await _get_scene(session, scene_id)
    key = scene.quicklooks.get(name.removesuffix(".webp"))
    if key is None:
        raise HTTPException(status_code=404, detail=f"У сцены нет превью {name}")
    body = await asyncio.to_thread(s3.get_bytes, key)
    return Response(body, media_type="image/webp", headers={"Cache-Control": QUICKLOOK_CACHE})


@router.post("/scenes/{scene_id}/reprocess", status_code=202, summary="Прогнать сцену через конвейер заново")
async def reprocess_scene(scene_id: str, session: Session) -> dict[str, str]:
    scene = await _get_scene(session, scene_id)
    job_id = await register_scene(session, {"id": scene.id, "kind": scene.kind, "files": scene.files})
    return {"job_id": str(job_id), "scene_id": scene_id}


async def _store_upload(upload: UploadFile, key: str, folder: Path) -> Path:
    path = folder / Path(key).name
    size = 0
    with path.open("wb") as handle:
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413, detail=f"Файл {upload.filename} больше {MAX_UPLOAD_BYTES // 2**20} МБ"
                )
            handle.write(chunk)
    return path


@router.post("/scenes", status_code=202, summary="Загрузить чип: файлы уходят в S3, задание в RabbitMQ")
async def upload_scene(
    session: Session,
    kind: Annotated[Literal["af", "bs"], Form()],
    scene_id: Annotated[str | None, Form(description="Идентификатор чипа. По умолчанию генерируется")] = None,
    acquired_at: Annotated[datetime | None, Form(description="Момент пролёта, только AF")] = None,
    satellite: Annotated[str | None, Form()] = None,
    date_pre: Annotated[date | None, Form(description="Дата снимка «до», только BS")] = None,
    date_post: Annotated[date | None, Form(description="Дата снимка «после», только BS")] = None,
    viirs: UploadFile | None = None,
    aux: UploadFile | None = None,
    s2_pre: UploadFile | None = None,
    s2_post: UploadFile | None = None,
    s1_pre: UploadFile | None = None,
    s1_post: UploadFile | None = None,
    mask: UploadFile | None = None,
) -> dict[str, str]:
    scene_id = scene_id or f"{kind.upper()}_up_{uuid.uuid4().hex[:8]}"
    if not SCENE_ID_PATTERN.match(scene_id):
        raise HTTPException(
            status_code=422, detail="scene_id: латиница, цифры, дефис и подчёркивание, 3-64 символа"
        )
    if kind == "af" and acquired_at is None:
        raise HTTPException(status_code=422, detail="Для AF-чипа укажите acquired_at")
    if kind == "bs" and (date_pre is None or date_post is None):
        raise HTTPException(status_code=422, detail="Для BS-чипа укажите date_pre и date_post")

    uploads = {
        "viirs": viirs,
        "aux": aux,
        "s2_pre": s2_pre,
        "s2_post": s2_post,
        "s1_pre": s1_pre,
        "s1_post": s1_post,
        "mask": mask,
    }
    missing = [role for role in required_roles(kind) if uploads[role] is None]
    if missing:
        raise HTTPException(status_code=422, detail=f"Не хватает файлов: {', '.join(missing)}")

    files: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="fw_upload_") as tmp:
        stored: dict[str, Path] = {}
        for role in (*required_roles(kind), *OPTIONAL_ROLES):
            if (upload := uploads[role]) is not None:
                files[role] = raw_key(kind, scene_id, role)
                stored[role] = await _store_upload(upload, f"{role}.tif", Path(tmp))
        try:
            await asyncio.to_thread(GeoRef.from_raster, stored[GEOREF_ROLE[kind]])
        except MissingGeoreferenceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Файл не читается как GeoTIFF: {exc}") from exc
        for role, path in stored.items():
            await asyncio.to_thread(s3.upload_file, path, files[role])

    job_id = await register_scene(
        session,
        {
            "id": scene_id,
            "kind": kind,
            "source": "upload",
            "acquired_at": acquired_at,
            "satellite": satellite,
            "date_pre": date_pre,
            "date_post": date_post,
            "files": files,
        },
    )
    return {"job_id": str(job_id), "scene_id": scene_id}


@router.get("/jobs", summary="Последние задания конвейера")
async def list_jobs(session: Session, limit: int = Query(30, ge=1, le=200)) -> dict[str, Any]:
    jobs = (await session.execute(select(Job).order_by(Job.created_at.desc()).limit(limit))).scalars().all()
    counts = dict((await session.execute(select(Job.status, func.count()).group_by(Job.status))).all())
    return {
        "counts": counts,
        "items": [
            {
                "id": str(j.id),
                "scene_id": j.scene_id,
                "status": j.status,
                "stage": j.stage,
                "progress": j.progress,
                "message": j.message,
                "created_at": j.created_at.isoformat(),
                "updated_at": j.updated_at.isoformat(),
            }
            for j in jobs
        ],
    }
