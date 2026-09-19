from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from firewatch.api.schemas import BBox
from firewatch.db.session import get_session
from firewatch.services import acquisitions, firms, hotspot_acquisition
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
    except InvalidQueryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # The two products are independent. A large territory can still receive FIRMS
    # hotspots even when the 20 m Sentinel analysis would exceed its four-chip budget.
    try:
        hotspot_result = await firms.import_hotspots(session, area, body.date_pre, body.date_post)
    except (firms.FirmsError, httpx.HTTPError) as exc:
        hotspot_result = {"status": "unavailable", "message": str(exc), "imported": 0, "existing": 0}

    try:
        jobs = await acquisitions.request_acquisition(session, area, body.date_pre, body.date_post)
        burn_result = {"status": "queued", "jobs": len(jobs)}
    except acquisitions.InvalidAcquisitionError as exc:
        jobs = []
        burn_result = {"status": "skipped", "message": str(exc), "jobs": 0}
    return {"jobs": jobs, "hotspots": hotspot_result, "burns": burn_result}
