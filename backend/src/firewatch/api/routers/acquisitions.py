from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from firewatch.api.schemas import BBox
from firewatch.db.session import get_session
from firewatch.services import acquisitions, hotspot_acquisition
from firewatch.services.query import InvalidQueryError, SpatioTemporalQuery, parse_geometry

router = APIRouter(prefix="/api/v1", tags=["Анализ новой области"])
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/events/{event_id}/acquisition")
async def hotspot_status(event_id: str, session: Session):
    return await hotspot_acquisition.state(session, event_id)


@router.post("/events/{event_id}/acquisition", status_code=202)
async def acquire_hotspot(event_id: str, session: Session, retry: bool = False):
    try:
        return await hotspot_acquisition.start(session, event_id, retry)
    except acquisitions.InvalidAcquisitionError as exc:
        raise HTTPException(422, str(exc)) from exc


class AcquisitionBody(BaseModel):
    """Область и две даты. Сервис сам найдёт ближайшие малооблачные сцены Sentinel-2 и соберёт чипы."""

    geometry: dict[str, Any] | None = Field(
        default=None, description="GeoJSON Polygon или MultiPolygon, WGS 84"
    )
    bbox: BBox | None = Field(default=None, description="west, south, east, north")
    date_pre: date = Field(description="Желаемая дата снимка «до»")
    date_post: date = Field(description="Желаемая дата снимка «после»")


@router.get(
    "/acquisitions/suggest", summary="Подсказать область: случайная точка или случайный очаг из архива"
)
async def suggest_area(session: Session, mode: Literal["random", "fire"] = "random") -> dict[str, Any]:
    return await acquisitions.suggest(session, mode)


@router.post(
    "/acquisitions",
    status_code=202,
    summary="Скачать Sentinel-2 по области и датам, собрать чипы и провести их через конвейер",
)
async def create_acquisition(body: AcquisitionBody, session: Session) -> dict[str, Any]:
    try:
        if body.geometry is not None:
            area = parse_geometry(body.geometry)
        else:
            query = SpatioTemporalQuery.build(
                geometry=None, bbox=body.bbox, date_from=body.date_pre, date_to=body.date_post
            )
            area = parse_geometry(query.geometry)
        jobs = await acquisitions.request_acquisition(session, area, body.date_pre, body.date_post)
    except (InvalidQueryError, acquisitions.InvalidAcquisitionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"jobs": jobs}
