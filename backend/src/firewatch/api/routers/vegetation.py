import asyncio
import json
import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from firewatch.db.session import get_session
from firewatch.infra import s3
from firewatch.infra.broker import VEGETATION_QUEUE, broker
from firewatch.infra.cache import redis
from firewatch.services import vegetation as v

router = APIRouter(prefix="/api/v1", tags=["Растительность после пожара"])
Session = Annotated[AsyncSession, Depends(get_session)]
JobId = Annotated[str, Path(pattern=r"^[a-f0-9]{32}$")]


async def stalled(report: dict) -> bool:
    age = (datetime.now(UTC) - datetime.fromisoformat(report["updated_at"])).total_seconds()
    if report["status"] == "queued":
        return age > 1800
    return (
        report["status"] == "running"
        and age > 180
        and not await redis.exists(f"fw:vegetation:worker:{report['id']}")
    )


@router.post("/events/{event_id}/vegetation", status_code=202)
async def start(event_id: str, session: Session, retry: bool = False):
    if event_id.startswith("af-"):
        raise HTTPException(422, "Для наблюдения нужен контур гари, а не только термоточка")
    if not event_id.startswith("bs-"):
        raise HTTPException(404, "Паспорт не найден")
    # Exact source polygons, never simplified map geometry or a bounding rectangle.
    row = (
        (
            await session.execute(
                text("""
        SELECT ST_AsGeoJSON(ST_UnaryUnion(ST_Collect(ST_MakeValid(geom)))) AS geometry,
               min(epsg) AS epsg, min(date_pre) AS date_from, max(date_post) AS date_to
        FROM burn_areas WHERE scene_id IN (
            SELECT id FROM scenes WHERE kind='bs' AND status='ready'
            AND coalesce(nullif(fire_event_id,''),id)=:event_key
        )
    """),
                {"event_key": event_id[3:]},
            )
        )
        .mappings()
        .one()
    )
    if not row["geometry"]:
        raise HTTPException(404, "Контур гари не найден")
    source = {
        "event_id": event_id,
        "geometry": json.loads(row["geometry"]),
        "epsg": row["epsg"],
        "date_from": str(row["date_from"]),
        "date_to": str(row["date_to"]),
    }
    try:
        years = v.years_for(source["date_from"])
        grid = await asyncio.to_thread(v.make_grid, source["geometry"], source["epsg"])
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    job = v.fingerprint(source, years)
    scenes = (
        (
            await session.execute(
                text("""
        SELECT files->>'s2_post' AS raster, quicklooks->>'rgb_post' AS rgb, date_post::text AS date
        FROM scenes WHERE kind='bs' AND status='ready'
        AND coalesce(nullif(fire_event_id,''),id)=:event_key
        AND files ? 's2_post' AND quicklooks ? 'rgb_post'
    """),
                {"event_key": event_id[3:]},
            )
        )
        .mappings()
        .all()
    )
    source["scenes"] = [dict(s) for s in scenes]
    lock, token = f"fw:vegetation:create:{job}", uuid.uuid4().hex
    if not await redis.set(lock, token, nx=True, ex=60):
        raise HTTPException(409, "Наблюдения уже создаются. Откройте ещё раз через пару секунд")
    try:
        report = await asyncio.to_thread(v.read_report, job)
        stale = report and await stalled(report)
        if report and (
            (report["status"] in {"queued", "running"} and not stale)
            or (
                not retry
                and report["status"] not in {"queued", "running"}
                and report.get("comparison_version") == 1
                and report.get("recent_checked") == str(date.today())
            )
        ):
            return v.public(report)
        if report is None:
            report = {
                "id": job,
                "event_id": event_id,
                "source": source,
                "created_at": v.now(),
                "years": years,
                "baseline_year": years[0],
                "season": "15 июня — 15 июля",
                "resolution_m": 20,
                "analyzed_ha": round(float(grid["mask"].sum()) * 0.04, 2),
                "frames": [],
                "active_year": None,
            }
        # Saved frames survive retries; only unavailable observations are fetched again.
        report["source"] = source
        if retry:
            report["recent_checked"] = None
        report.update(status="queued", message=None)
        await asyncio.to_thread(v.save_report, report)
        try:
            await broker.publish({"job_id": job}, queue=VEGETATION_QUEUE, persist=True)
        except Exception as exc:
            report.update(status="error", message="Очередь загрузки недоступна")
            await asyncio.to_thread(v.save_report, report)
            raise HTTPException(503, "Не удалось поставить загрузку в очередь") from exc
        return v.public(report)
    finally:
        await v.unlock(lock, token)


@router.get("/vegetation/{job_id}")
async def get_report(job_id: JobId):
    report = await asyncio.to_thread(v.read_report, job_id)
    if report is None:
        raise HTTPException(404, "Наблюдения не найдены")
    result = v.public(report)
    if await stalled(report):
        result.update(status="error", message="Загрузка прервалась. Повторите запрос")
    return result


@router.get("/vegetation/{job_id}/observation/{kind}.webp")
async def observation(job_id: JobId, kind: Literal["post", "recent"]):
    name = v.key(job_id, f"{kind}-rgb.webp")
    if not await asyncio.to_thread(s3.exists, name):
        raise HTTPException(404, "Изображение ещё не готово")
    return Response(
        await asyncio.to_thread(s3.get_bytes, name),
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.get("/vegetation/{job_id}/{year}/{kind}.webp")
async def image(job_id: JobId, year: Annotated[int, Path(ge=2017, le=2100)], kind: Literal["rgb", "change"]):
    name = v.key(job_id, f"{year}-{kind}.webp")
    if not await asyncio.to_thread(s3.exists, name):
        raise HTTPException(404, "Изображение ещё не готово")
    return Response(
        await asyncio.to_thread(s3.get_bytes, name),
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=300"},
    )
