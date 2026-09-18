from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from geoalchemy2.shape import from_shape, to_shape
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from firewatch.api.schemas import ZoneCreate
from firewatch.db.models import Alert, Zone
from firewatch.db.session import get_session
from firewatch.services.query import InvalidQueryError, parse_geometry

router = APIRouter(prefix="/api/v1", tags=["Зоны наблюдения и алерты"])
Session = Annotated[AsyncSession, Depends(get_session)]


def _zone_json(zone: Zone) -> dict[str, Any]:
    return {
        "id": zone.id,
        "name": zone.name,
        "geometry": to_shape(zone.geom).__geo_interface__,
        "webhook_url": zone.webhook_url,
        "created_at": zone.created_at.isoformat(),
    }


@router.get("/zones", summary="Зоны наблюдения")
async def list_zones(session: Session) -> list[dict[str, Any]]:
    return [_zone_json(z) for z in (await session.execute(select(Zone).order_by(Zone.id))).scalars()]


@router.post("/zones", status_code=201, summary="Создать зону: алерт придёт в интерфейс и на webhook")
async def create_zone(body: ZoneCreate, session: Session) -> dict[str, Any]:
    try:
        geom = parse_geometry(body.geometry)
    except InvalidQueryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    zone = Zone(
        name=body.name,
        geom=from_shape(geom, srid=4326),
        webhook_url=str(body.webhook_url) if body.webhook_url else None,
    )
    session.add(zone)
    await session.commit()
    return _zone_json(zone)


@router.delete("/zones/{zone_id}", status_code=204, summary="Удалить зону")
async def delete_zone(zone_id: int, session: Session) -> None:
    result = await session.execute(delete(Zone).where(Zone.id == zone_id))
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Зона не найдена")
    await session.commit()


@router.get("/alerts", summary="Алерты по зонам наблюдения")
async def list_alerts(session: Session, limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(Alert, Zone.name, func.ST_AsGeoJSON(Alert.centroid))
            .join(Zone, Zone.id == Alert.zone_id)
            .order_by(Alert.created_at.desc())
            .limit(limit)
        )
    ).all()
    unread = (
        await session.execute(select(func.count()).select_from(Alert).where(Alert.is_read.is_(False)))
    ).scalar_one()
    return {
        "unread": unread,
        "items": [
            {
                "id": alert.id,
                "zone_id": alert.zone_id,
                "zone_name": zone_name,
                "scene_id": alert.scene_id,
                "n_hotspots": alert.n_hotspots,
                "acquired_at": alert.acquired_at.isoformat(),
                "created_at": alert.created_at.isoformat(),
                "is_read": alert.is_read,
                "lon": json.loads(centroid)["coordinates"][0],
                "lat": json.loads(centroid)["coordinates"][1],
            }
            for alert, zone_name, centroid in rows
        ],
    }


@router.post("/alerts/read", status_code=204, summary="Отметить все алерты прочитанными")
async def mark_alerts_read(session: Session) -> None:
    await session.execute(update(Alert).where(Alert.is_read.is_(False)).values(is_read=True))
    await session.commit()
