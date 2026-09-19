from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from shapely.geometry import shape
from shapely.prepared import prep
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from firewatch.api.schemas import GetQuery, QueryBody
from firewatch.db.session import get_session
from firewatch.infra.cache import cached
from firewatch.services import events

router = APIRouter(prefix="/api/v1/events", tags=["Паспорта пожаров"])
Session = Annotated[AsyncSession, Depends(get_session)]
Status = Literal["all", "linked", "hotspot_only", "burn_only", "ambiguous"]


async def _list(session, query, status, offset, limit):
    data = await events.index(session)
    matching_scenes = set(
        (
            await session.execute(
                text("""
        SELECT DISTINCT scene_id FROM burn_areas
        WHERE ST_Intersects(geom,ST_SetSRID(ST_GeomFromGeoJSON(:geometry),4326))
          AND date_pre<=:date_to AND date_post>=:date_from
    """),
                query.sql_params,
            )
        ).scalars()
    )
    area = prep(shape(query.geometry))
    selected = [
        e
        for e in data["events"]
        if (status == "all" or e["status"] == status) and events.in_query(e, query, matching_scenes, area)
    ]
    selected.sort(key=lambda e: (e["date_to"], e["id"]), reverse=True)
    return {
        "total": len(selected),
        "items": [events.summary(e) for e in selected[offset : offset + limit]],
        "offset": offset,
        "limit": limit,
        "method": data["method"],
    }


@router.post("", summary="Паспорта по территории и периоду")
async def list_events(
    body: QueryBody,
    session: Session,
    status: Status = "all",
    offset: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
):
    return await _list(session, body.to_query(), status, offset, limit)


@router.get("", summary="Паспорта по bbox и периоду")
async def get_events(
    query: GetQuery,
    session: Session,
    status: Status = "all",
    offset: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
):
    return await _list(session, query, status, offset, limit)


@router.get("/resolve", summary="Найти паспорт по термоточке или сцене гари")
async def resolve(session: Session, hotspot_id: int | None = Query(None, ge=1), scene_id: str | None = None):
    if (hotspot_id is None) == (scene_id is None):
        raise HTTPException(422, "Укажите ровно одно поле: hotspot_id или scene_id")
    data = await events.index(session)
    for e in data["events"]:
        if (scene_id and scene_id in e["scene_ids"]) or (
            hotspot_id and any(h["id"] == hotspot_id for h in e["hotspots"])
        ):
            return {"id": e["id"]}
    raise HTTPException(
        404, "Для этого наблюдения паспорт не найден. Обновите карту; отсеянные точки в паспорта не входят."
    )


@router.get("/{event_id}", summary="История, основания связи, гарь и восстановление")
async def get_event(event_id: str, session: Session):
    data = await events.index(session)
    event = next((e for e in data["events"] if e["id"] == event_id), None)
    if event is None:
        raise HTTPException(404, "Паспорт не найден. После обновления данных откройте список заново.")
    return await cached(
        "event-detail",
        [events.INDEX_VERSION, event_id],
        lambda: events.detail(session, event, data["method"]),
    )
